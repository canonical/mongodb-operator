import secrets
import string
import subprocess

from tenacity import retry, stop_after_delay
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError
import logging


logger = logging.getLogger(__name__)

# We expect the mongodb container to use the
# default ports
MONGODB_PORT = 27017


class MongoDB():

    def __init__(self, config):
        self.app_name = config['app_name']
        self.replica_set_name = config['replica_set_name']
        self.num_peers = config['num_peers']
        self.port = config['port']
        self.root_password = config['root_password']
        self.unit_ips = config['unit_ips']

    def enable(self) -> None:
        """Enable the mongoDB service via systemd.
        Returns:
            None: None
        """
        subprocess.check_call(["systemctl", "enable", "mongod.service"])
        subprocess.check_call(["systemctl", "restart", "mongod.service"])

    def client(self):
        """Construct a client for the MongoDB database.

        The timeout for all queries using this client object is 1 sec.

        Retruns:
            A pymongo :class:`MongoClient` object.
        """
        return MongoClient(self.replica_set_uri(), serverSelectionTimeoutMS=1000)
    
    @retry(stop=stop_after_delay(20))
    def is_ready(self):
        """Is the MongoDB server ready to services requests.

        Returns:
            True if services is ready False otherwise.
        """
        ready = False
        client = self.client()
        try:
            client.server_info()
            ready = True
        except ServerSelectionTimeoutError as e:
            # TODO change this back to debug
            logger.error("mongodb service is not ready yet. %s",e)
            client.close()
            raise e
        finally:
            client.close()
        return ready

    def initialize_replica_set(self, hosts: list):
        """Initialize the MongoDB replica set.

        Args:
            hosts: a list of peer host addresses
        """
        config = {
            "_id": self.replica_set_name,
            "members": [{"_id": i, "host": h} for i, h in enumerate(hosts)],
        }
        logger.debug("setting up replica set with these options %s",config)
        client = self.client()
        try:
            client.admin.command("replSetInitiate", config)
        except Exception as e:
            logger.error("cannot initialize replica set. error={}".format(e))
            raise e
        finally:
            client.close()

    def replica_set_uri(self, credentials=None):
        """Construct a replica set URI.

        Args:
            credentials: an optional dictionary with keys "username"
            and "password"

        Returns:
            A string URI that may be used to access the MongoDB
            replica set.
        """
        if credentials:
            password = credentials["password"]
            username = credentials["username"]
        else:
            password = self.root_password
            username = "root"

        #uri = "mongodb://{}:{}@".format(
        #    username,
        #    password)
        
        uri = "mongodb://"
        for i, host in enumerate(self.unit_ips):
            if i:
                uri += ","
            # TODO remove once able to use actual host
            # host = "localhost"
            uri += "{}:{}".format(host, self.port)
        uri += "/"#admin"
        logger.error("uri %s",uri)
        return uri

    @staticmethod
    def new_password():
        """Generate a random password string.
        Returns:
           A random password string.
        """
        choices = string.ascii_letters + string.digits
        pwd = "".join([secrets.choice(choices) for i in range(16)])
        return pwd
