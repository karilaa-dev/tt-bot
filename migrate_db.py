import asyncio
import logging
import os
import re
import sqlite3
import time
from configparser import ConfigParser
from contextlib import closing

import asyncpg

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load configuration
config = ConfigParser()
config.read("config.ini")

# --- Configuration ---
SQLITE_DB_PATH = 'sqlite.db'
POSTGRES_DSN = config['bot']['db_url']
CHUNK_SIZE = 100000
# --- End Configuration ---

# --- Transformation Functions ---

def transform_user_data(sqlite_row_dict):
    """Transforms a single row dictionary from SQLite users to PostgreSQL users format."""
    return {
        'user_id': sqlite_row_dict.get('id'),
        'registered_at': sqlite_row_dict.get('time'),
        'lang': sqlite_row_dict.get('lang'),
        'link': sqlite_row_dict.get('link'),
        'file_mode': bool(sqlite_row_dict.get('file_mode'))
    }


def transform_music_data(sqlite_row_dict):
    """
    Transforms a single row dictionary from SQLite music to PostgreSQL music format.
    Handles conversion of 'video' from TEXT/VARCHAR to int8.
    Returns None for records where 'video' column contains non-numeric values.
    """
    sqlite_video = sqlite_row_dict.get('video')
    pg_video = None

    if sqlite_video is not None:
        try:
            pg_video = int(sqlite_video)
        except (ValueError, TypeError):
            logging.warning(
                f"Skipping record: music.video value '{sqlite_video}' is text "
                f"for user_id {sqlite_row_dict.get('id')}."
            )
            return None

    return {
        'user_id': sqlite_row_dict.get('id'),
        'downloaded_at': sqlite_row_dict.get('time'),
        'video_id': pg_video
        # pk_id is auto-generated in PostgreSQL
    }


def transform_video_data(sqlite_row_dict):
    """Transforms a single row dictionary from SQLite videos to PostgreSQL videos format."""
    return {
        'user_id': sqlite_row_dict.get('id'),
        'downloaded_at': sqlite_row_dict.get('time'),
        'video_link': sqlite_row_dict.get('video'),
        'is_images': bool(sqlite_row_dict.get('is_images', False)) # Default to False if None, as PG column is NOT NULL
        # pk_id is auto-generated in PostgreSQL
    }


# --- Thread-Safe SQLite Fetching Function ---
def fetch_sqlite_chunk_thread_safe(db_path, table_name, chunk_size, offset):
    """
    Connects to SQLite, fetches a chunk of data, and returns it as dicts.
    Intended to be run in a separate thread via asyncio.to_thread.
    """
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Add PRAGMA settings for potentially faster reads
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA temp_store = MEMORY;")
            cursor.execute("PRAGMA cache_size = -200000;")  # Advise SQLite to use 200,000 KiB (~195.3 MiB) for cache
            cursor.execute("PRAGMA mmap_size = 268435456;") # Enable memory-mapped I/O up to 256MB

            logging.debug(f"Executing SELECT * FROM {table_name} LIMIT {chunk_size} OFFSET {offset}")
            cursor.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (chunk_size, offset))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logging.error(f"SQLite error fetching chunk from {table_name}: {e}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"Unexpected error fetching chunk from {table_name}: {e}", exc_info=True)
        return None


# --- Core Migration Logic ---
async def migrate_table(sqlite_db_path, pg_pool, sqlite_table_name, pg_table_name, pg_columns, transform_func):
    """Migrates data from an SQLite table to a PostgreSQL table asynchronously."""
    logging.info(f"Migration process started for: {sqlite_table_name} -> {pg_table_name}")
    processed_rows_total = 0
    skipped_rows_total = 0
    current_offset = 0

    try:
        while True:
            logging.debug(f"Requesting chunk from {sqlite_table_name} (offset: {current_offset})...")
            sqlite_rows_dicts = await asyncio.to_thread(
                fetch_sqlite_chunk_thread_safe,
                sqlite_db_path,
                sqlite_table_name,
                CHUNK_SIZE,
                current_offset
            )

            if sqlite_rows_dicts is None:
                logging.error(f"Migration failed for {sqlite_table_name} due to fetch error.")
                break

            if not sqlite_rows_dicts:
                logging.debug(f"No more rows found in {sqlite_table_name} at offset {current_offset}.")
                break

            logging.debug(f"Fetched {len(sqlite_rows_dicts)} rows. Processing chunk for {pg_table_name}...")
            data_to_insert = []
            for row_dict in sqlite_rows_dicts:
                try:
                    transformed_data = transform_func(row_dict)
                    if transformed_data is None:
                        skipped_rows_total += 1
                        continue
                    ordered_values = tuple(transformed_data.get(col) for col in pg_columns)
                    data_to_insert.append(ordered_values)
                except Exception as e:
                    logging.error(f"Error transforming row for {pg_table_name}: {row_dict}. Error: {e}", exc_info=True)
                    continue

            if data_to_insert:
                async with pg_pool.acquire() as conn:
                    try:
                        await conn.copy_records_to_table(
                            pg_table_name,
                            records=data_to_insert,
                            columns=pg_columns,
                            timeout=300
                        )
                        chunk_rows = len(data_to_insert)
                        processed_rows_total += chunk_rows
                        logging.debug(
                            f"Copied chunk ({chunk_rows} rows) into {pg_table_name}. Total: {processed_rows_total}")
                        current_offset += len(sqlite_rows_dicts)

                    except asyncpg.PostgresError as e:
                        logging.error(f"Error using COPY for chunk into {pg_table_name}: {e}", exc_info=True)
                        logging.error(
                            f"Failed data sample (first row if available): {data_to_insert[0] if data_to_insert else 'N/A'}")
                        # Consider how to handle errors with COPY.
                        # For simplicity, this example stops processing the current table on error.
                        # You might implement retries or skip problematic chunks.
                        return processed_rows_total
                    except Exception as e:
                        logging.error(f"Unexpected error during COPY for {pg_table_name}: {e}", exc_info=True)
                        return processed_rows_total
            else:
                logging.warning(
                    f"No valid data to insert into {pg_table_name} from the fetched chunk (offset {current_offset}).")
                current_offset += len(sqlite_rows_dicts)

        logging.info(
            f"Migration process finished for {sqlite_table_name} -> {pg_table_name}. Total rows migrated: {processed_rows_total}, Skipped rows: {skipped_rows_total}")
        return processed_rows_total

    except asyncpg.PostgresError as e:
        logging.error(f"PostgreSQL error during migration of {sqlite_table_name}: {e}", exc_info=True)
        logging.info(f"Rows processed before error: {processed_rows_total}, Skipped rows: {skipped_rows_total}")
        return processed_rows_total
    except Exception as e:
        logging.error(f"Unexpected error during migration of {sqlite_table_name}: {e}", exc_info=True)
        logging.info(f"Rows processed before error: {processed_rows_total}, Skipped rows: {skipped_rows_total}")
        return processed_rows_total


# --- Timing Wrapper ---
async def run_migration_with_timing(table_alias, *migration_args):
    """Wraps migrate_table call to measure and log execution time."""
    start_time = time.perf_counter()
    logging.info(f"--- Starting migration for table: {table_alias} ---")
    try:
        total_rows = await migrate_table(*migration_args)
        end_time = time.perf_counter()
        duration = end_time - start_time
        logging.info(f"--- Finished migration for table: {table_alias}. "
                     f"Migrated {total_rows} rows. Took {duration:.2f} seconds. ---")
    except Exception as e:
        end_time = time.perf_counter()
        duration = end_time - start_time
        logging.error(f"--- Migration failed for table: {table_alias} after {duration:.2f} seconds. Error: {e} ---",
                      exc_info=True)


# --- Sequence Reset Function ---
async def reset_postgres_sequences(pg_pool):
    """Resets PostgreSQL sequences for serial/bigserial columns."""
    logging.info("Attempting to reset PostgreSQL sequences...")
    tables_to_check = {
        'music': 'pk_id',
        'videos': 'pk_id'
    }

    async with pg_pool.acquire() as conn:
        try:
            table_check_sql = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                AND table_name = ANY($1);
            """
            existing_tables = await conn.fetch(table_check_sql, list(tables_to_check.keys()))
            existing_table_names = [t['table_name'] for t in existing_tables]

            if not existing_table_names:
                logging.warning("None of the specified tables exist for sequence reset. Skipping.")
                return

            logging.info(f"Found existing tables for sequence reset: {existing_table_names}")

            for table in existing_table_names:
                column = tables_to_check[table]
                sequence_name = None
                try:
                    # Check if the column exists and get its default value
                    column_info_sql = """
                        SELECT column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = $1
                        AND column_name = $2;
                    """
                    column_info = await conn.fetchrow(column_info_sql, table, column)

                    if not column_info:
                        logging.warning(f"Column {column} not found in table {table}. Skipping sequence reset for this column.")
                        continue

                    if column_info['column_default'] and 'nextval' in column_info['column_default']:
                        match = re.search(r"nextval\('([^']+)'::regclass\)", column_info['column_default'])
                        if match:
                            sequence_name = match.group(1)
                            logging.info(f"Found sequence '{sequence_name}' for {table}.{column} from column default.")

                    if not sequence_name:
                        # Fallback: try to get sequence name using pg_get_serial_sequence
                        sequence_name_sql = f"SELECT pg_get_serial_sequence('public.{table}', '{column}');"
                        sequence_name = await conn.fetchval(sequence_name_sql)
                        if sequence_name:
                             logging.info(f"Found sequence '{sequence_name}' for {table}.{column} using pg_get_serial_sequence.")
                        else:
                            logging.warning(f"Could not determine sequence name for {table}.{column}. Skipping reset.")
                            continue
                    
                    # Reset the sequence
                    async with conn.transaction():
                        logging.info(f"Resetting sequence '{sequence_name}' for {table}.{column}...")
                        reset_sql = f"""
                            SELECT setval(
                                '{sequence_name}',
                                COALESCE((SELECT MAX({column}) FROM {table}), 0) + 1,
                                (SELECT MAX({column}) IS NOT NULL FROM {table})
                            );
                        """
                        await conn.execute(reset_sql)
                        logging.info(f"Sequence '{sequence_name}' reset successfully.")

                except asyncpg.PostgresError as e:
                    logging.error(f"PostgreSQL error processing sequence for {table}.{column}: {e}", exc_info=True)
                except Exception as e:
                    logging.error(f"Unexpected error processing sequence for {table}.{column}: {e}", exc_info=True)
        except Exception as e:
            logging.error(f"Error checking database tables for sequence reset: {e}", exc_info=True)

        logging.info("Sequence reset process completed.")


# --- Main Orchestration ---
async def main():
    """Main async function to orchestrate the migration."""
    pg_pool = None
    overall_start_time = time.perf_counter()

    if not os.path.exists(SQLITE_DB_PATH):
        logging.error(f"SQLite database file not found at: {SQLITE_DB_PATH}")
        return

    try:
        logging.info(f"Creating PostgreSQL connection pool for DSN starting with: {POSTGRES_DSN[:POSTGRES_DSN.find('@') if '@' in POSTGRES_DSN else 20]}...") # Log DSN prefix for security
        pg_pool = await asyncpg.create_pool(dsn=POSTGRES_DSN, min_size=1, max_size=10)
        logging.info("PostgreSQL connection pool created successfully.")

        # --- Migrate users table (Sequentially first due to FKs) ---
        users_pg_columns = ['user_id', 'registered_at', 'lang', 'link', 'file_mode']
        await run_migration_with_timing(
            'users',
            SQLITE_DB_PATH, pg_pool, 'users', 'users', users_pg_columns, transform_user_data
        )

        # --- Migrate music and videos tables (Concurrently) ---
        logging.info("--- Starting parallel migration phase for music and videos ---")
        parallel_start_time = time.perf_counter()

        music_pg_columns = ['user_id', 'downloaded_at', 'video_id']
        videos_pg_columns = ['user_id', 'downloaded_at', 'video_link', 'is_images']

        music_task = asyncio.create_task(
            run_migration_with_timing(
                'music',
                SQLITE_DB_PATH, pg_pool, 'music', 'music', music_pg_columns, transform_music_data
            )
        )
        videos_task = asyncio.create_task(
            run_migration_with_timing(
                'videos',
                SQLITE_DB_PATH, pg_pool, 'videos', 'videos', videos_pg_columns, transform_video_data
            )
        )

        await asyncio.gather(music_task, videos_task)

        parallel_end_time = time.perf_counter()
        logging.info(f"--- Parallel migration phase (music, videos) finished. "
                     f"Took {parallel_end_time - parallel_start_time:.2f} seconds overall. ---")

        await reset_postgres_sequences(pg_pool)

    except asyncpg.exceptions.InvalidPasswordError:
        logging.error("PostgreSQL connection error: Invalid password.")
    except asyncpg.exceptions.CannotConnectNowError:
        logging.error("PostgreSQL connection error: Cannot connect now. Is the server running?")
    except ConnectionRefusedError:
        # Construct DSN prefix for logging, being careful if '@' is not present
        dsn_prefix_match = re.match(r"postgresql://([^:]+):[^@]+@([^/]+)/(.+)", POSTGRES_DSN)
        host_info = "host information not parsed"
        if dsn_prefix_match:
            host_info = f"user '{dsn_prefix_match.group(1)}' at host '{dsn_prefix_match.group(2)}' for database '{dsn_prefix_match.group(3)}'"
        else: # Fallback if DSN format is unexpected
             at_index = POSTGRES_DSN.find('@')
             if at_index != -1:
                 host_info = POSTGRES_DSN[at_index+1:] # Get part after @
                 slash_index = host_info.find('/')
                 if slash_index != -1:
                     host_info = host_info[:slash_index] # Get part before / in the host string


        logging.error(f"PostgreSQL connection error: Connection refused. Check connection to {host_info}.")
    except Exception as e:
        logging.error(f"An critical error occurred during the main migration orchestration: {e}", exc_info=True)
    finally:
        if pg_pool:
            logging.info("Closing PostgreSQL connection pool...")
            await pg_pool.close()
            logging.info("PostgreSQL connection pool closed.")

        overall_end_time = time.perf_counter()
        logging.info(
            f"--- Database migration script finished. Total elapsed time: {overall_end_time - overall_start_time:.2f} seconds ---")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "Cannot run the event loop while another loop is running" in str(e):
            # Provide a more user-friendly message for this common asyncio issue.
            logging.error("Failed to start migration: Detected an already running event loop. "
                          "This script should be run in a context without an active asyncio loop.")
        else:
            # Re-raise other runtime errors for standard traceback.
            raise
