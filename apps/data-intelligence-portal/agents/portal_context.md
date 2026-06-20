# Data Intelligence Portal Context

The Data Intelligence Portal is a cloneable template for contract-aware data platform visibility.

It demonstrates:
- Source domains publishing agreed events through Kafka topic names.
- Protobuf contracts that define event shape and primary keys.
- Marker-based ingestion that starts only after data is published.
- Deduplication using the primary keys declared by each event.
- Historical catalog layers named intraday, endofday, and analytics.
- Data lineage from source topic to catalog table.
- Process lineage from marker to ingestion run to catalog write.

The default demo domain is retail commerce with orders, payments, and shipments.
