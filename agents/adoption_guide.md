# Adoption Guide Agent Notes

To adapt the portal for a new workplace:

1. Add domain metadata in `demo/contracts.json`.
2. Add Protobuf contracts under `contracts/protobuf/<domain>/`.
3. Add sample event files under `demo/events/<domain>/`.
4. Add marker files under `demo/markers/`.
5. Configure primary keys for deduplication.
6. Run demo ingestion and inspect catalog, lineage, and process lineage views.

Production adapters can replace the demo marker reader with Kafka consumers and replace local object-store writes with Iceberg table writes.
