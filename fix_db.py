import logging
import os
import sqlite3
from contextlib import closing

# --- Configuration ---
SQLITE_DB_PATH = 'sqlite.db'  # Path to your SQLite database file
# --- End Configuration ---

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def add_missing_users(db_path):
    """
    Finds IDs in music/videos tables that are missing from the users table
    and inserts new user records for them with NULL values for optional fields.
    """
    logging.info(f"Starting process to add missing users to {db_path}...")
    missing_ids_added = 0

    if not os.path.exists(db_path):
        logging.error(f"Database file not found at: {db_path}")
        return 0

    try:
        # Use closing for automatic connection closing
        with closing(sqlite3.connect(db_path)) as conn:
            cursor = conn.cursor()
            logging.info("Successfully connected to SQLite database.")

            # 1. Get all unique non-null IDs from music and videos tables
            logging.info("Fetching distinct IDs from 'music' table...")
            cursor.execute("SELECT DISTINCT id FROM music WHERE id IS NOT NULL;")
            music_ids = {row[0] for row in cursor.fetchall()}
            logging.info(f"Found {len(music_ids)} distinct IDs in 'music'.")

            logging.info("Fetching distinct IDs from 'videos' table...")
            cursor.execute("SELECT DISTINCT id FROM videos WHERE id IS NOT NULL;")
            videos_ids = {row[0] for row in cursor.fetchall()}
            logging.info(f"Found {len(videos_ids)} distinct IDs in 'videos'.")

            # Combine IDs from both tables
            required_user_ids = music_ids.union(videos_ids)
            logging.info(
                f"Found {len(required_user_ids)} distinct IDs required in 'users' based on 'music' and 'videos'.")

            # 2. Get all existing IDs from the users table
            logging.info("Fetching existing IDs from 'users' table...")
            cursor.execute("SELECT id FROM users WHERE id IS NOT NULL;")
            existing_user_ids = {row[0] for row in cursor.fetchall()}
            logging.info(f"Found {len(existing_user_ids)} existing IDs in 'users'.")

            # 3. Find which required IDs are missing from the users table
            missing_ids = required_user_ids - existing_user_ids
            logging.info(f"Found {len(missing_ids)} user IDs that are missing from the 'users' table.")

            # 4. Insert missing users if any are found
            if not missing_ids:
                logging.info("No missing user IDs found. The 'users' table is consistent with 'music' and 'videos'.")
                return 0

            logging.info(f"Preparing to insert {len(missing_ids)} missing user records...")

            # Prepare data for executemany: list of tuples, each tuple containing one ID
            data_to_insert = [(missing_id,) for missing_id in missing_ids]

            # SQL statement to insert a user with the required ID and NULL for other fields
            # Based on SQLite DDL [2], columns are: id, time, lang, link, file_mode
            insert_sql = """
                INSERT INTO users (id, time, lang, link, file_mode)
                VALUES (?, NULL, 'en', NULL, 0);
            """

            # Perform insertions in a transaction
            try:
                logging.info("Executing bulk insert for missing users...")
                cursor.executemany(insert_sql, data_to_insert)
                conn.commit()  # Commit the transaction
                missing_ids_added = len(missing_ids)
                logging.info(f"Successfully inserted {missing_ids_added} missing user records.")
            except sqlite3.Error as insert_error:
                logging.error(f"Error during bulk insert of missing users: {insert_error}", exc_info=True)
                logging.warning("Rolling back transaction due to insertion error.")
                conn.rollback()  # Rollback on error
                return 0  # Return 0 as no users were successfully added in the end

    except sqlite3.Error as e:
        logging.error(f"An SQLite error occurred: {e}", exc_info=True)
        return 0  # Indicate failure or no users added due to error
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        return 0  # Indicate failure

    return missing_ids_added


if __name__ == "__main__":
    added_count = add_missing_users(SQLITE_DB_PATH)
    logging.info(f"--- Script finished. Total missing users added: {added_count} ---")
