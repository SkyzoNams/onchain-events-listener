import logging
import time
import threading
import eth_event
from web3 import Web3
from src.utils import get_dict_file
from src.database_manager import DataBase_Manager
from dotenv import load_dotenv
load_dotenv()
logging.addLevelName(24, "CONNECTION")
logging.addLevelName(25, "BLOCKS INFO")
logging.addLevelName(26, "DATABASE")


class Events_Listener():
    def __init__(self):
        # Contract ABI for decoding events
        self.contract_abi = get_dict_file("./files/abi.json")
        self.topic_map = eth_event.get_topic_map(self.contract_abi)
        # Contract address to listen for events on
        self.contract_address = "0xBAac2B4491727D78D2b78815144570b9f2Fe8899"
        # Web3 instance for connecting to the provider
        self.web3 = None
        # Thread pool for fetch_events_in_blocks
        self.threads = []
        self.max_threads = 8
        self.last_stored_block_number = None


    def connect_to_provider(self):
        """
        @Notice: This function is used to connect the contract to the web3 provider
        @Dev: We first create a web3 instance linked to the Infura provider and then we instantiate
        the contract using the web3 provider
        """
        try:
            time.sleep(0.01)
            self.web3 = Web3(Web3.HTTPProvider(
                "https://mainnet.infura.io/v3/0a49990ca1114f4da1bdfa3fb8bdccff"))
            tries = 5
            # Check for connection and retry if unsuccessful
            while self.web3.isConnected() is False and tries >= 0:
                logging.info("waiting for web3 connection...")
                time.sleep(2)
                self.web3 = Web3(Web3.HTTPProvider(
                    "https://mainnet.infura.io/v3/0a49990ca1114f4da1bdfa3fb8bdccff"))
                tries -= 1
            time.sleep(0.01)
            return self.web3
        except Exception as e:
            raise e

    def provider(self):
        """
        @Notice: This function will check for existing web3 connection or connect to the provider
        @Return: web3 instance
        """
        if self.web3 is None or self.web3.isConnected() is False:
            return self.connect_to_provider()
        return self.web3

    def fetch_events(self):
        """
        @Notice: This function will listen for new blocks to explore
        @Dev: We first define from which block to start the exploration by checking on the recorded last block file.
        We call the fetch_events_in_blocks method to explore the blocks.
        """
        try:
            last_processed_block_number = None
            while 42:
                last_processed_block_number, last_block_number = self.get_last_processed_block_number(last_processed_block_number)
                logging.log(25, "from #" + str(last_processed_block_number) +
                            " to #" + str(last_block_number))
                last_processed_block_number = self.fetch_events_in_blocks(
                    last_processed_block_number, last_block_number)
                self.waiting_for_new_blocks(
                    last_processed_block_number, last_block_number)
        except Exception as e:
            raise e

    def fetch_events_in_blocks(
            self, last_processed_block_number: int, last_block_number: int):
        """
        @Notice: Iterate over block numbers to decode their transaction hashes and find events
        @param: last_processed_block_number: int : the last block number that was processed
        @param: last_block_number: int : the last block number on the blockchain
        @return: int : the last processed block number
        @Dev: If the last_block_number is None, we get the last block number on the blockchain. Then, we start a new thread for the current block only if the thread pool is not full, otherwise we wait for a thread to finish. We return the last processed block number
        """
        try:
            if last_block_number is None:
                last_block_number = self.get_last_block_number()
            while last_processed_block_number <= last_block_number:
                # Wait for a thread to finish if the thread pool is full
                while len(self.threads) >= self.max_threads:
                    for t in self.threads:
                        if not t.is_alive():
                            self.threads.remove(t)
                # Start a new thread for the current block
                t = threading.Thread(target=self.explore_block, args=(
                    last_processed_block_number,))
                t.start()
                self.threads.append(t)
                last_processed_block_number += 1
            return last_processed_block_number
        except Exception as e:
            raise e

    def explore_block(self, block_num: int):
        """
        @Notice: This function will search for events in the given block number
        @param block_num: The block number to explore
        @Dev: We get the block by calling the get_block method on the web3 provider, then we call the decode_block_transactions_hash method to decode the block's transaction hashes and find events. Finally, we write the last processed block number to the recorded block file.
        """
        logging.info("searching events on block #" + str(block_num))
        block = self.provider().eth.get_block(block_num)
        self.decode_block_transactions_hash(block, block_num)
        
    def decode_block_transactions_hash(
            self, current_block, current_block_number: int):
        """
        @Notice: This method will decode the transaction hashes in a block to find events
        @param current_block: The current block to explore
        @param current_block_number: The current block number
        @Dev: We iterate over the block's transaction hashes and for each one, we call the get_transaction_receipt method on the web3 provider to get the transaction receipt, then we iterate over the logs in the receipt and try to decode them using the topic_map. If the log is successfully decoded, we print the decoded event.
        """
        for tx_hash in current_block['transactions']:
            receipt = self.provider().eth.get_transaction_receipt(tx_hash)
            if self.is_one_of_us(receipt):
                try:
                    events = eth_event.decode_logs(
                        receipt.logs, self.topic_map)
                except BaseException:
                    continue
                if events:
                    self.handle_event(events, tx_hash.hex())

    def is_one_of_us(self, receipt):
        """
        @Notice: This function is used to check if the contract address we are looking for is on the receipt
        @param: receipt: the transaction receipt
        @return: bool: True if the contract_address is on the receipt, False otherwise
        @Dev: We check if the receipt's 'to' field or 'contractAddress' field is not None and equal to the contract address we are looking for
        """
        return (receipt['to'] is not None and receipt['to'] == self.contract_address) or (receipt['contractAddress'] is not None and receipt['contractAddress'] == self.contract_address)

    def waiting_for_new_blocks(self, last_processed_block_number, last_block_number):
        """
        @Notice: This function is used to wait for new blocks to be mined and return the latest block number
        @param: last_processed_block_number: the last block number that was processed
        @param: last_block_number: the last block number available
        @Dev: We keep checking for new blocks until the last_block_number is less than last_processed_block_number. We then return the last_block_number
        """
        logging.log(25, "waiting for not explored blocks...")
        while last_block_number < last_processed_block_number:
            last_block_number = self.provider().eth.get_block('latest')[
                'number']
        logging.log(25, "new blocks found, will explore now from #" +
                    str(last_processed_block_number) + " to #" + str(last_block_number))

    def get_last_processed_block_number(self, last_processed_block_number):
        """
        @Notice: This function will return the last processed block number from the recorded block file
        @return: The last processed block number and the current block number
        """
        try:
            last_block_number = self.get_last_block_number()
            if last_processed_block_number is None:
                last_processed_block_number = last_block_number
            return last_processed_block_number, last_block_number
        except Exception as e:
            raise e

    def get_last_block_number(self):
        """
        @Notice: This function will return the current block number from the provider
        @return: The current block number
        @Dev: We call the getBlockNumber method on the web3 provider and return the result
        """
        return int(self.provider().eth.get_block('latest')['number'])

    def handle_event(self, events, transaction_hash: str):
        """
        @Notice: This function handle events and update the balance of the addresses in the user_balance table
        @param events: The events that need to be handled
        @param current_block_number: current block number
        @param transaction_hash: transaction hash
        @Dev: This function uses the insert_user_ballance function to insert/update the balance of the addresses
        """
        for event in events:
            if event['name'] == "Transfer":
                self.insert_user_ballance(event['data'][0]['value'], transaction_hash)
                self.insert_user_ballance(event['data'][1]['value'], transaction_hash)
            
    def get_balance(self, address):
        """
        @Notice: This function returns the balance of a specific ERC20 token for a specific address
        @param address: The address you want to get the balance of
        @return: The balance of the address in the token's unit
        """
        # Create the contract object
        contract = self.get_contract()
        # The function that returns the balance of the address
        balance_of_function = contract.functions.balanceOf(Web3.toChecksumAddress(address))
        # Call the function and get the balance
        return balance_of_function.call()
    
    def insert_user_ballance(self, address, transaction_hash):
        """
        @Notice: This function insert or updates the balance of a specific address 
        in the user_balance table.
        @param address: The address you want to insert/update the balance
        @Dev: This function uses the get_balance function to get the balance of the address
        """
        DataBase_Manager().execute("""INSERT INTO user_balance (balance, address, transaction_hash)
            SELECT %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM user_balance
                WHERE address = %s AND transaction_hash = %s);""", (self.get_balance(address), address, transaction_hash, address, transaction_hash))
        logging.log(26, "new record inserted")
        

    def get_contract(self):
        """
        @Notice: This function returns the contract object
        @Dev: This function uses the provider method to connect to the Ethereum network
        @return: contract object
        """
        # Create the contract object
        return self.provider().eth.contract(address=self.contract_address, abi=self.contract_abi)

    def get_total_supply(self):
        """
        @Notice: This function returns the total supply of the ERC20 token
        @Dev: This function uses the get_contract function to get the contract object
        @return: total supply of the ERC20 token
        """
        contract = self.get_contract()
        # The function that returns the total supply
        total_supply_function = contract.functions.totalSupply()
        # Call the function and get the total supply
        return total_supply_function.call()

    def get_holders(self, limit=None):
        query = """WITH last_created AS (
            SELECT address, max(created_at) as last_created
            FROM user_balance
            GROUP BY address
        )
        SELECT user_balance.*
        FROM user_balance
        JOIN last_created
        ON user_balance.address = last_created.address
        AND user_balance.created_at = last_created.last_created"""
        if limit is not None:
            query +=  " LIMIT " + str(limit)

    def get_top_100_holders(self):
        query = "SELECT * FROM user_balance ORDER BY balance ASC LIMIT 100"
    
    def get_holders_weekly_change(self, limit=None):
        query = """WITH weekly_change AS (
            SELECT address,
                balance - lag(balance) over (partition by address order by created_at) as weekly_change
            FROM user_balance
        )
        SELECT *, weekly_change
        FROM weekly_change"""
        if limit is not None:
            query +=  " LIMIT " + str(limit)
    