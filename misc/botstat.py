import aiohttp
import logging

from data.config import config, admin_ids
from misc.utils import get_users_file


class Botstat:
    def __init__(self):
        self.token = config['bot']['token']
        self.botstat = config['api']['botstat']
        self.request_url = f"https://api.botstat.io/create/{self.token}/{self.botstat}"
        self.request_params = {
            "notify_id": admin_ids[0],
            "hide": "false",
            "show_file_result": "true"
        }

    async def start_task(self):
        logging.info("Starting botstat task...")
        logging.debug("Attempting to get users file.")
        request_file = await get_users_file()
        logging.info("Successfully retrieved users file.")

        form_data = aiohttp.FormData()
        form_data.add_field("file", request_file.data, filename=request_file.filename, content_type="text/plain")
        logging.debug("Form data prepared.")

        try:
            logging.info(f"Sending request to Botstat API")
            async with aiohttp.ClientSession() as client:
                async with client.post(self.request_url,
                params=self.request_params, data=form_data) as response:
                    code = response.status
                    logging.info(f"Received response with status code: {code}")
                    if code != 200:
                        logging.error(f"API error code: {code}")
                        raise Exception(f'API error code:{code}')
            logging.info("Botstat task completed successfully.")
        except Exception as e:
            logging.error(f"Exception during botstat task: {e}", exc_info=True)
            raise e