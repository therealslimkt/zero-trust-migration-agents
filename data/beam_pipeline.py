
import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions

def decode_ebcdic(element):
    """Decodes a line of EBCDIC data to ASCII."""
    return element.decode('ibm037')

def run():
    """Runs the Beam pipeline."""
    with beam.Pipeline(options=PipelineOptions()) as p:
        (p
         | 'ReadEBCDIC' >> beam.io.ReadFromText("/Users/kohalloran/Documents/hackathons/all_things_agentic/zero-trust-migration-agents/data/F0101_address_book.bin", coder=beam.coders.BytesCoder())
         | 'DecodeEBCDIC' >> beam.Map(decode_ebcdic)
         | 'PrintOutput' >> beam.Map(print)
        )

if __name__ == '__main__':
    run()
