# Charmed MongoDB tutorial:
Ready to try out Charmed MongoDB? This tutorial will guide you through the steps to get Charmed MongoDB up and running. 

## Minimum requirements:
Before we start be sure you have the following requirements:
- Ubuntu 20.04(focal) or later.
- 8GB of RAM.
- 2 CPU threads.
- At least 20GB of available storage.
- Access to the internet for downloading the required snaps and charms.

## Install and prepare LXD:
The fastest, simplest way to get started with Charmed MongoDB is to set up a local LXD cloud. The first step on our journey is to install LXD. LXD is installed from a snap package:
```
sudo snap install lxd --classic
```

Next we need to run lxd init to perform post-installation tasks. For this tutorial the default parameters are preferred and the network bridge should be set to have no ipv6 addresses:
```
lxd init --auto
lxc network set lxdbr0 ipv6.address none 
```

In the next step we will install Juju. Juju speaks directly to the local LXD daemon, which also requires [lxd group membership](https://linuxcontainers.org/lxd/getting-started-cli/#access-control). Add `$USER` to the group lxd:
```
newgrp lxd
sudo adduser $USER lxd
```

## Install and prepare Juju:
[Juju](https://juju.is/) is an operation Lifecycle manager(OLM) for clouds, bare metal or Kubernetes. We will be using it to deploy and manage Charmed MongoDB. As with LXD, Juju is installed from a snap package:
```
sudo snap install juju --classic
```

Juju already has a built-in knowledge of LXD and how it works, so there is no additional setup or configuration needed. A controller will be used to deploy and control Charmed MongoDB. \ All we need to do is run the command to bootstrap a Juju controller named ‘overlord’ to LXD. 
```
juju bootstrap localhost overlord
```

The controller can work with different models; models host applications such as Charmed MongoDB. Set up a specific model for Charmed MongoDB named ‘tutorial’:
```
juju add-model tutorial
```

