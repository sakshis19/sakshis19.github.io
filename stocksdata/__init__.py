import logging
import yfinance as yf
import pandas as pd
from datetime import datetime
import azure.functions as func
from azure.storage.blob import BlobServiceClient
import io
import os

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # Get ticker, period, and interval from query parameters, with defaults
    # For example: ?ticker=MSFT&period=1d&interval=1m
    ticker = req.params.get('ticker')
    if not ticker:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            ticker = req_body.get('ticker')

    if not ticker:
        ticker = 'AAPL' # Default ticker if not provided

    period = req.params.get('period') or '1d' # Default period is 1 day
    interval = req.params.get('interval') or '1m' # Default interval is 1 minute

    try:
        logging.info(f"Fetching data for {ticker} with period={period}, interval={interval}")
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval=interval)

        if hist.empty:
            logging.warning(f"No data returned from yfinance for {ticker}")
            return func.HttpResponse("No data returned from yfinance for the specified ticker/period/interval.", status_code=204)

        # Reset index to make 'Datetime' a column and prepare CSV in-memory
        hist.reset_index(inplace=True)
        csv_buffer = io.StringIO()
        hist.to_csv(csv_buffer, index=False) # Write DataFrame to a CSV string

        # Get connection string from application settings
        # AzureWebJobsStorage is the default connection string for the storage account linked to your Function App
        # You added this in the previous step.
        connect_str = os.getenv("AzureWebJobsStorage")
        if not connect_str:
            logging.error("AzureWebJobsStorage connection string not found in app settings.")
            return func.HttpResponse("Storage connection string not configured.", status_code=500)

        blob_service_client = BlobServiceClient.from_connection_string(connect_str)

        # Ensure your container name matches what you created (e.g., 'stock-data' or 'stockfiles')
        container_name = "stock-data" # <--- IMPORTANT: Verify this matches your container name
        container_client = blob_service_client.get_container_client(container_name)

        # Create container if it doesn't exist (optional, but good for robustness)
        try:
            container_client.create_container()
            logging.info(f"Container '{container_name}' created (if it didn't exist).")
        except Exception as e:
            if "ContainerAlreadyExists" not in str(e):
                logging.error(f"Error creating container: {e}")
                return func.HttpResponse(f"Error creating blob container: {e}", status_code=500)
            logging.info(f"Container '{container_name}' already exists.")


        # Define the blob path: ticker/YYYY-MM-DD_HHMMSS.csv
        # Using UTC time is best practice for cloud applications
        now_utc = datetime.utcnow().strftime('%Y-%m-%d_%H%M%S')
        filename = f"{ticker}/{now_utc}.csv" # Example: AAPL/2025-07-23_225424.csv

        blob_client = blob_service_client.get_blob_client(container=container_name, blob=filename)

        # Upload the CSV data to the blob
        blob_client.upload_blob(csv_buffer.getvalue(), overwrite=True)
        logging.info(f"Data for {ticker} uploaded to blob: {filename}")

        return func.HttpResponse(
            f"Successfully fetched and uploaded data for {ticker} to {filename} in Blob Storage.",
            status_code=200
        )

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        return func.HttpResponse(
            f"An error occurred while processing your request: {str(e)}",
            status_code=500
        )