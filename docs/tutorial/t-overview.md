# Charmed MongoDB tutorial

The Charmed MongoDB Operator delivers automated operations management from [day 0 to day 2](https://codilime.com/blog/day-0-day-1-day-2-the-software-lifecycle-in-the-cloud-age/) on the [MongoDB Community Edition](https://github.com/mongodb/mongo) document database. It is an open source, end-to-end, production-ready data platform [on top of Juju](https://juju.is/). As a first step this tutorial shows you how to get Charmed MongoDB up and running, but the tutorial does not stop there. Through this tutorial you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transcript Layer Security (TLS). In this tutorial we will walk through how to:
- Set up your environment using LXD and Juju.
- Deploy MongoDB using a single command.
- Access the admin database directly.
- Add high availability with replication.
- Change the admin password.
- Automatically create MongoDB users via Juju relations. 
- Enable secure transactions with TLS.

While this tutorial intends to guide and teach you as you deploy Charmed MongoDB, it will be most beneficial if you already have a familiarity with: 
- Basic terminal commands.
- MongoDB concepts such as replication and users.

## Step-by-step guide

Here’s an overview of the steps required with links to our separate tutorials that deal with each individual step:
* [Set up the environment](/t/charmed-mongodb-tutorial-environment-setup/8622?channel=dpe/edge)
* [Deploy MongoDB](/t/charmed-mongodb-tutorial-deploy-mongodb/8621?channel=dpe/edge)
* [Managing your units](/t/charmed-mongodb-tutorial-managing-units/8620?channel=dpe/edge)
* [Manage passwords](/t/charmed-mongodb-tutorial-manage-passwords/8630?channel=dpe/edge)
* [Relate your MongoDB to other applications](/t/charmed-mongodb-tutorial-relate-your-mongodb-deployment/8629?channel=dpe/edge)
* [Enable security](/t/charmed-mongodb-tutorial-enable-security/8628?channel=dpe/edge)
* [Cleanup your environment](/t/charmed-mongodb-tutorial-environment-cleanup/8627?channel=dpe/edge)

## License
The Charmed MongoDB Operator is distributed under the Apache Software License, version 2.0. It [installs/operates/depends on] [MongoDB Community Edition](https://github.com/mongodb/mongo), which is licensed under the Server Side Public License (SSPL).

## Trademark Notice
MongoDB™ is a trademark or registered trademark of MongoDB Inc. Other trademarks are property of their respective owners.