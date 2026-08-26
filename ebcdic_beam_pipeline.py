
import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
import json
import logging

# Set up logging for better visibility
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

# --- Configuration Constants ---
# These would typically be passed as pipeline options or environment variables
EBCDIC_CODEPAGE = 'cp037' # Common EBCDIC codepage
BIGQUERY_TABLE = 'your_gcp_project:your_bq_dataset.your_bq_table' # Replace with your BigQuery table
INPUT_FILE_PATTERN = 'gs://your-input-bucket/ebcdic-data.txt' # Replace with your input data path
# Example record length for fixed-length EBCDIC records
# This comes from the COBOL copybook or data definition.
# For our hypothetical CUSTOMER-RECORD:
# CUSTOMER-ID (S9(7) COMP-3) = 4 bytes (2 digits per byte + 1/2 byte for sign)
# CUSTOMER-NAME (X(30)) = 30 bytes
# CUSTOMER-STATUS (X(1)) = 1 byte
# TRANSACTION-AMOUNT (S9(13)V99 COMP-3) = 9 bytes (13 digits + 2 decimals = 15 digits, 8 full bytes + 1/2 byte for sign)
# Total = 4 + 30 + 1 + 9 = 44 bytes
RECORD_LENGTH = 44


# --- DoFn for EBCDIC to UTF-8 Decoding ---
class DecodeEBCDIC(beam.DoFn):
    """
    Decodes EBCDIC byte strings into UTF-8 strings.
    Assumes fixed-length records for now, if not reading line by line.
    """
    def __init__(self, codepage):
        self.codepage = codepage

    def process(self, element):
        try:
            # element is expected to be a byte string (e.g., from TextIO.read_as_bytes)
            decoded_string = element.decode(self.codepage)
            _LOGGER.debug(f"Decoded EBCDIC: {element[:10]}... to ASCII: {decoded_string[:10]}...")
            yield decoded_string
        except Exception as e:
            _LOGGER.error(f"Error decoding EBCDIC data: {element}. Error: {e}")
            # Optionally, yield to a dead-letter queue
            # yield beam.pvalue.TaggedOutput('dead_letter_ebcdic_decode', {'raw_ebcdic': element, 'error': str(e)})

# --- DoFn for Parsing Records based on COBOL Copybook definition ---
class ParseCustomerRecord(beam.DoFn):
    """
    Parses a decoded EBCDIC string (now UTF-8) into a structured dictionary.
    This logic heavily depends on the COBOL Copybook/Data Definition.
    For demonstration, we use a hypothetical fixed-length record structure.
    Packed decimal and other non-character field parsing would be complex here.
    """
    def process(self, element):
        try:
            # element is a UTF-8 string representing one fixed-length record
            # In a real scenario, you'd use a library like 'ebcdic-parser' or
            # custom logic to handle offsets and data types (e.g., packed decimals).

            # Hypothetical fixed-length parsing (assuming all fields are EBCDIC characters decoded to ASCII)
            # This is a simplification; actual EBCDIC often mixes character and binary/packed decimal.
            # E.g., for packed decimal, you'd extract byte slices *before* EBCDIC decoding and
            # then use specific functions to convert packed decimal bytes to integers/floats.

            customer_id_str = element[0:4] # Placeholder for packed decimal, assuming it was char
            customer_name = element[4:34].strip()
            customer_status = element[34:35].strip()
            transaction_amount_str = element[35:44] # Placeholder for packed decimal

            # For packed decimals, you'd need a specific conversion function like:
            # customer_id_bytes = element_original_bytes[0:4] # Need original bytes for this
            # customer_id = convert_packed_decimal(customer_id_bytes)

            # For now, let's just make up some values if we can't parse directly
            try:
                customer_id = int(customer_id_str) # This would fail for actual packed decimal bytes if not handled correctly
            except ValueError:
                customer_id = -1 # Or a default

            try:
                # Example: S9(13)V99 COMP-3 -> 15 digits total, last two are decimal.
                # If parsed as string, might need to insert decimal point
                transaction_amount = float(transaction_amount_str) # This would also likely fail for packed decimal bytes
            except ValueError :
                transaction_amount = 0.0

            record = {
                'customer_id': customer_id,
                'customer_name': customer_name,
                'customer_status': customer_status,
                'transaction_amount': transaction_amount,
                'processing_timestamp': beam.pipeline.Row.from_kwargs(
                    format='RFC3339',
                    value=beam.timestamp.Timestamp(beam.do_fn.DoFn.StartBundleContext.current_timestamp()).isoformat()
                )
            }
            _LOGGER.debug(f"Parsed record: {record}")
            yield record
        except Exception as e:
            _LOGGER.error(f"Error parsing record: {element}. Error: {e}")
            # yield beam.pvalue.TaggedOutput('dead_letter_parse_error', {'raw_utf8': element, 'error': str(e)})

# --- Main Apache Beam Pipeline ---
def run_pipeline(argv=None):
    pipeline_options = PipelineOptions(argv)

    # BigQuery schema for the output table
    # This must match the structure of the dictionaries yielded by ParseCustomerRecord
    table_schema = {
        'fields': [
            {'name': 'customer_id', 'type': 'INTEGER', 'mode': 'REQUIRED'},
            {'name': 'customer_name', 'type': 'STRING', 'mode': 'NULLABLE'},
            {'name': 'customer_status', 'type': 'STRING', 'mode': 'NULLABLE'},
            {'name': 'transaction_amount', 'type': 'FLOAT', 'mode': 'NULLABLE'},
            {'name': 'processing_timestamp', 'type': 'TIMESTAMP', 'mode': 'NULLABLE'},
        ]
    }

    with beam.Pipeline(options=pipeline_options) as p:
        (p
         | 'ReadEBCDICData' >> beam.io.ReadFromText(INPUT_FILE_PATTERN, coder=beam.coders.BytesCoder())
         # If records are fixed length and not line-delimited, you'd read bytes directly
         # and then chunk them into records before decoding as seen below.
         # For simplicity, assuming each line is one EBCDIC record.
         # If not line-delimited:
         # | 'ReadFullFileBytes' >> beam.io.ReadFromBinary(INPUT_FILE_PATTERN)
         # | 'ChunkIntoRecords' >> beam.FlatMap(lambda full_bytes: [full_bytes[i:i+RECORD_LENGTH] for i in range(0, len(full_bytes), RECORD_LENGTH)])


         | 'DecodeEBCDICRecords' >> beam.ParDo(DecodeEBCDIC(EBCDIC_CODEPAGE))
         | 'ParseCustomerRecords' >> beam.ParDo(ParseCustomerRecord())
         | 'WriteToBigQuery' >> beam.io.WriteToBigQuery(
               BIGQUERY_TABLE,
               schema=table_schema,
               create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED,
               write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND
           ))

if __name__ == '__main__':
    # When running locally, install 'apache-beam[gcp]'
    # python -m apache_beam.runners.direct.direct_runner --runner=DirectRunner --input=your_local_ebcdic_file.txt
    # When deploying to Dataflow:
    # python your_beam_pipeline.py --runner=DataflowRunner --project=your_project_id --region=your_region --temp_location=gs://your-temp-bucket/temp/ --input=gs://your-input-bucket/ebcdic-data.txt

    # Example of how to run this from the command line:
    # python -c 'import your_pipeline_module; your_pipeline_module.run_pipeline()'
    # Or, if saved as ebcdic_beam_pipeline.py:
    # python ebcdic_beam_pipeline.py
    run_pipeline()
