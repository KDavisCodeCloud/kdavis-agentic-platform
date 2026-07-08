# Schema Validations

Per-agent input/output JSON schemas, read by `core/assertion.py`.

Add one file per agent named `{agent_name}.json`, using standard JSON Schema
`required` and `properties` (with `type`) keys. An agent with no file here
is not schema-checked — coverage is opt-in, not mandatory.
