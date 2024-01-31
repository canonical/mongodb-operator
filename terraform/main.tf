resource "juju_application" "mongodb-k8s" {
  name  = "mongodb-k8s"
  model = var.model_name

  charm {
    name    = "mongodb-k8s"
    channel = var.channel
    base    = "ubuntu@22.04"
  }
  config = var.mongo-config
  units  = 1
  trust  = true
}
