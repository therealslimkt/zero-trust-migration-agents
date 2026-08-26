# EBCDIC to BigQuery Pipeline

This directory contains an Apache Beam pipeline to decode EBCDIC data and prepare it for ingestion into Google BigQuery.

## `beam_pipeline.py`

This script defines a simple Beam pipeline that:

1.  Reads raw EBCDIC data from a binary file (`F0101_address_book.bin`).
2.  Decodes the data from the `ibm037` EBCDIC codepage to ASCII.
3.  Prints the decoded data to the console.

### Usage

To run the pipeline, execute the following command from the `data` directory:

```
python3 beam_pipeline.py
```

### Next Steps

This is a basic pipeline that can be extended to:

*   Read from a streaming source like Pub/Sub.
*   Write the decoded data to a BigQuery table.
*   Implement error handling for records that fail to decode.
*   Use a schema to structure the data for BigQuery.
