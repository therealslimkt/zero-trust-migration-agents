import argparse
import logging
import json
import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.options.pipeline_options import SetupOptions

class EBCDICDecoderDoFn(beam.DoFn):
    """
    A custom Apache Beam worker function that simulates the decoding 
    of an EBCDIC/COMP-3 proprietary binary payload.
    In production, this would invoke the JTOpen JAR or native decoders.
    """
    def process(self, element):
        try:
            # element represents a scrubbed raw string from the Edge Agents
            raw_text = element.strip()
            if not raw_text:
                return

            # Simulate binary format extraction based on known offsets
            # e.g., 'EBCDIC_RECORD: 1004 Clark Kent SSN: [SSN_BLOCKED_AT_EDGE] EMAIL: [EMAIL_BLOCKED]'
            parts = raw_text.split(" ")
            
            # Map the parsed data into a standard Python dictionary
            parsed_record = {
                "record_id": parts[1] if len(parts) > 1 else "UNKNOWN",
                "name": f"{parts[2]} {parts[3]}" if len(parts) > 3 else "UNKNOWN",
                "ssn": parts[5] if len(parts) > 5 else "MISSING",
                "email": parts[7] if len(parts) > 7 else "MISSING",
                "source_system": "IBM_AS400",
                "status": "PII_SECURED"
            }
            
            yield parsed_record
            
        except Exception as e:
            logging.error(f"Failed to decode EBCDIC payload: {e}")

def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', dest='input', required=True, help='Input path to the raw data stream.')
    parser.add_argument('--output_table', dest='output_table', required=True, help='BigQuery Table ID (e.g. project:dataset.table)')
    
    known_args, pipeline_args = parser.parse_known_args(argv)
    pipeline_options = PipelineOptions(pipeline_args)
    pipeline_options.view_as(SetupOptions).save_main_session = True

    # Define the strict BigQuery Schema
    bq_schema = {
        'fields': [
            {'name': 'record_id', 'type': 'STRING', 'mode': 'REQUIRED'},
            {'name': 'name', 'type': 'STRING', 'mode': 'NULLABLE'},
            {'name': 'ssn', 'type': 'STRING', 'mode': 'NULLABLE'},
            {'name': 'email', 'type': 'STRING', 'mode': 'NULLABLE'},
            {'name': 'source_system', 'type': 'STRING', 'mode': 'REQUIRED'},
            {'name': 'status', 'type': 'STRING', 'mode': 'REQUIRED'},
        ]
    }

    # Build the Dataflow Pipeline
    with beam.Pipeline(options=pipeline_options) as p:
        (
            p
            # 1. Ingest the raw data (Simulating the feed from Edge Agents)
            | 'Read Raw Edge Stream' >> beam.io.ReadFromText(known_args.input)
            
            # 2. Decode the proprietary binary
            | 'Decode EBCDIC via JTOpen' >> beam.ParDo(EBCDICDecoderDoFn())
            
            # 3. Stream directly into Google BigQuery
            | 'Write to BigQuery' >> beam.io.WriteToBigQuery(
                known_args.output_table,
                schema=bq_schema,
                write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED
            )
        )

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    print("🚀 Initializing Zero-Trust Apache Beam Translation Pipeline...")
    run()
