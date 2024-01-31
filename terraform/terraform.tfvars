# Mandatory Config Options
model_name = "put your model-name here"

# Optional Configuration
channel = "put the charm channel here"
mongo-config = {
  auto-delete = "put True to remove any relevant databases associated with the relation when a relation is removed"
  role        = "put role config here as shard, config-server or replication"
}
