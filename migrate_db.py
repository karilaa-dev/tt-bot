import asyncio
import asyncpg
import sqlite3
import logging
import os
import time # Import the time module
from contextlib import closing

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
SQLITE_DB_PATH = 'sqlite-full.db'
POSTGRES_USER = 'postgres'
POSTGRES_PASSWORD = 'postgres'
POSTGRES_HOST = 'postgres-dev.orb.local'
POSTGRES_DB = 'ttgrab'
POSTGRES_PORT = 5432
POSTGRES_DSN = f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}'
CHUNK_SIZE = 1000
# --- End Configuration ---

# --- Transformation Functions ---

def transform_user_data(sqlite_row_dict):
    """Transforms a single row dictionary from SQLite users to PostgreSQL users format."""
    return {
        'user_id': sqlite_row_dict.get('id'),
        'registered_at': sqlite_row_dict.get('time'), # INTEGER -> bigint/int8 [1, 2]
        'lang': sqlite_row_dict.get('lang'),
        'link': sqlite_row_dict.get('link'),
        # Convert SQLite INTEGER (assuming 0/1) to Boolean, handle None [1, 2]
        'file_mode': bool(sqlite_row_dict['file_mode']) if sqlite_row_dict.get('file_mode') is not None else None
    }

def transform_music_data(sqlite_row_dict):
    """
    Transforms a single row dictionary from SQLite music to PostgreSQL music format.
    Handles conversion of 'video' from TEXT/VARCHAR [2] to int8 [user DDL].
    """
    sqlite_video = sqlite_row_dict.get('video')
    pg_video = None # Default to NULL if conversion fails or source is NULL

    if sqlite_video is not None:
        try:
            # Attempt conversion to integer, assuming it's a numeric string in SQLite
            pg_video = int(sqlite_video)
        except (ValueError, TypeError):
            # Log a warning if conversion fails
            logging.warning(
                f"Could not convert music.video value '{sqlite_video}' to int "
                f"for user_id {sqlite_row_dict.get('id')}. Setting to NULL."
            )
            # pg_video remains None

    return {
        'user_id': sqlite_row_dict.get('id'), # Foreign Key [1]
        'downloaded_at': sqlite_row_dict.get('time'), # INTEGER -> bigint/int8 [1, 2]
        'video_id': pg_video # Use the converted integer or None
        # pk_id is auto-generated in PostgreSQL [user DDL]
    }

def transform_video_data(sqlite_row_dict):
    """Transforms a single row dictionary from SQLite videos to PostgreSQL videos format."""
    is_images_val = sqlite_row_dict.get('is_images')
    return {
        'user_id': sqlite_row_dict.get('id'), # Foreign Key [1]
        'downloaded_at': sqlite_row_dict.get('time'), # INTEGER -> bigint/int8 [1, 2]
        'video_link': sqlite_row_dict.get('video'),
        # Convert SQLite INTEGER (0/1) to Boolean, default False if None (PG NOT NULL) [1, 2]
        'is_images': bool(is_images_val) if is_images_val is not None else False
        # pk_id is auto-generated in PostgreSQL [1]
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
            logging.debug(f"[Thread] Executing SELECT * FROM {table_name} LIMIT {chunk_size} OFFSET {offset}")
            cursor.execute(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (chunk_size, offset))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logging.error(f"[Thread] SQLite error fetching chunk from {table_name}: {e}", exc_info=True)
        return None
    except Exception as e:
        logging.error(f"[Thread] Unexpected error fetching chunk from {table_name}: {e}", exc_info=True)
        return None

# --- Core Migration Logic ---
async def migrate_table(sqlite_db_path, pg_pool, sqlite_table_name, pg_table_name, pg_columns, transform_func):
    """
    Migrates data from an SQLite table to a PostgreSQL table asynchronously.
    (Now includes internal logging for start/finish, but timing is handled externally)
    """
    # Note: External timing wrapper will log start/end and duration.
    # Logging internally focuses on progress and potential issues.
    logging.info(f"Migration process started for: {sqlite_table_name} -> {pg_table_name}")
    processed_rows_total = 0
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
                    ordered_values = tuple(transformed_data.get(col) for col in pg_columns)
                    data_to_insert.append(ordered_values)
                except Exception as e:
                    logging.error(f"Error transforming row for {pg_table_name}: {row_dict}. Error: {e}", exc_info=True)
                    continue

            if data_to_insert:
                placeholders = ', '.join([f'${i+1}' for i in range(len(pg_columns))])
                insert_sql = f"INSERT INTO {pg_table_name} ({', '.join(pg_columns)}) VALUES ({placeholders})"

                async with pg_pool.acquire() as conn:
                    async with conn.transaction():
                        try:
                            await conn.executemany(insert_sql, data_to_insert)
                            chunk_rows = len(data_to_insert)
                            processed_rows_total += chunk_rows
                            logging.debug(f"Inserted chunk ({chunk_rows} rows) into {pg_table_name}. Total: {processed_rows_total}")
                            current_offset += chunk_rows # Use actual inserted rows count
                        except Exception as e:
                            logging.error(f"Error inserting chunk into {pg_table_name}: {e}", exc_info=True)
                            logging.error(f"Failed data sample (first row): {data_to_insert[0] if data_to_insert else 'N/A'}")
                            logging.error(f"Transaction rolled back for {pg_table_name}.")
                            # Stop processing this table on insertion error
                            return processed_rows_total # Return rows processed so far
            else:
                 logging.warning(f"No valid data to insert into {pg_table_name} from the fetched chunk (offset {current_offset}).")
                 # Advance offset even if transformations failed for all rows in chunk
                 current_offset += len(sqlite_rows_dicts)


        logging.info(f"Migration process finished for {sqlite_table_name} -> {pg_table_name}. Total rows migrated: {processed_rows_total}")
        return processed_rows_total # Return total count on success

    except asyncpg.PostgresError as e:
         logging.error(f"PostgreSQL error during migration of {sqlite_table_name}: {e}", exc_info=True)
         return processed_rows_total # Return count before error
    except Exception as e:
         logging.error(f"Unexpected error during migration of {sqlite_table_name}: {e}", exc_info=True)
         return processed_rows_total # Return count before error


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
        # Catch potential errors bubbled up from migrate_table if not handled internally
        end_time = time.perf_counter()
        duration = end_time - start_time
        logging.error(f"--- Migration failed for table: {table_alias} after {duration:.2f} seconds. Error: {e} ---", exc_info=True)


# --- Sequence Reset Function ---
async def reset_postgres_sequences(pg_pool):
    """Resets PostgreSQL sequences for serial/bigserial columns."""
    logging.info("Attempting to reset PostgreSQL sequences...")
    # Using new DDL for music table [user DDL]
    sequences_to_reset = {
        'users': 'user_id',
        'music': 'pk_id', # pk_id is the serial key for music [user DDL]
        'videos': 'pk_id' # pk_id is the serial key for videos [1]
    }
    async with pg_pool.acquire() as conn:
        try:
            async with conn.transaction():
                for table, column in sequences_to_reset.items():
                    try:
                        sequence_name_sql = f"SELECT pg_get_serial_sequence('{table}', '{column}');"
                        seq_name = await conn.fetchval(sequence_name_sql)
                        if seq_name:
                            logging.info(f"Resetting sequence '{seq_name}' for {table}.{column}...")
                            reset_sql = f"""
                                SELECT setval(
                                    pg_catalog.quote_ident('{seq_name}'),
                                    COALESCE((SELECT MAX({column}) FROM {table}), 0) + 1,
                                    (SELECT MAX({column}) IS NOT NULL FROM {table})
                                );
                            """
                            await conn.execute(reset_sql)
                            logging.info(f"Sequence '{seq_name}' reset successfully.")
                        else:
                            logging.warning(f"Could not determine sequence name for {table}.{column}. Skipping reset.")
                    except asyncpg.PostgresError as e:
                         logging.error(f"Error resetting sequence for {table}.{column}: {e}", exc_info=True)
                    except Exception as e:
                         logging.error(f"Unexpected error resetting sequence for {table}.{column}: {e}", exc_info=True)
            logging.info("Sequence reset process completed successfully.")
        except Exception as e:
            logging.error(f"Error during sequence reset transaction: {e}", exc_info=True)


# --- Main Orchestration ---
async def main():
    """Main async function to orchestrate the migration."""
    pg_pool = None
    overall_start_time = time.perf_counter()

    if not os.path.exists(SQLITE_DB_PATH):
         logging.error(f"SQLite database file not found at: {SQLITE_DB_PATH}")
         return

    try:
        logging.info(f"Creating PostgreSQL connection pool for {POSTGRES_DSN}...")
        pg_pool = await asyncpg.create_pool(dsn=POSTGRES_DSN, min_size=1, max_size=10)
        logging.info("PostgreSQL connection pool created successfully.")

        # --- Migrate users table (Sequentially first due to FKs) ---
        users_pg_columns = ['user_id', 'registered_at', 'lang', 'link', 'file_mode']
        await run_migration_with_timing(
            'users', # Alias for logging
            SQLITE_DB_PATH, pg_pool, 'users', 'users', users_pg_columns, transform_user_data
        )

        # --- Migrate music and videos tables (Concurrently) ---
        logging.info("--- Starting parallel migration phase for music and videos ---")
        parallel_start_time = time.perf_counter()

        # Define columns based on PostgreSQL DDL [1, user DDL]
        music_pg_columns = ['user_id', 'downloaded_at', 'video_id'] # pk_id is auto-gen
        videos_pg_columns = ['user_id', 'downloaded_at', 'video_link', 'is_images'] # pk_id is auto-gen

        # Create tasks for concurrent execution
        music_task = asyncio.create_task(
            run_migration_with_timing(
                'music', # Alias
                SQLITE_DB_PATH, pg_pool, 'music', 'music', music_pg_columns, transform_music_data
            )
        )
        videos_task = asyncio.create_task(
            run_migration_with_timing(
                'videos', # Alias
                SQLITE_DB_PATH, pg_pool, 'videos', 'videos', videos_pg_columns, transform_video_data
            )
        )

        # Wait for both concurrent tasks to complete
        await asyncio.gather(music_task, videos_task)

        parallel_end_time = time.perf_counter()
        logging.info(f"--- Parallel migration phase (music, videos) finished. "
                     f"Took {parallel_end_time - parallel_start_time:.2f} seconds overall. ---")

        # --- Reset sequences (After all data is inserted) ---
        await reset_postgres_sequences(pg_pool)

    except asyncpg.exceptions.InvalidPasswordError:
        logging.error("PostgreSQL connection error: Invalid password.")
    except asyncpg.exceptions.CannotConnectNowError:
         logging.error("PostgreSQL connection error: Cannot connect now. Is the server running?")
    except ConnectionRefusedError:
         logging.error(f"PostgreSQL connection error: Connection refused. Check host '{POSTGRES_HOST}' and port '{POSTGRES_PORT}'.")
    except Exception as e:
        logging.error(f"An critical error occurred during the main migration orchestration: {e}", exc_info=True)
    finally:
        if pg_pool:
            logging.info("Closing PostgreSQL connection pool...")
            await pg_pool.close()
            logging.info("PostgreSQL connection pool closed.")

        overall_end_time = time.perf_counter()
        logging.info(f"--- Database migration script finished. Total elapsed time: {overall_end_time - overall_start_time:.2f} seconds ---")


if __name__ == "__main__":
    # Ensure any previous loops are handled if run in certain environments,
    # but typically asyncio.run() is sufficient for scripts.
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "Cannot run the event loop while another loop is running" in str(e):
             print("Detected running event loop. Please run this script in a context without an active asyncio loop.")
        else:
             raise # Re-raise other runtime errors