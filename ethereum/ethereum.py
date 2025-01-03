from web3 import Web3
from datetime import datetime

w3 = Web3(Web3.HTTPProvider('https://eth-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR'))

ERC20_ABI = [
    {"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"}
]

def decode_uint256(hex_data):
    return int.from_bytes(hex_data, byteorder='big')

def decode_address(hex_data):
    raw_address = '0x' + hex_data[-20:].hex()
    return Web3.to_checksum_address(raw_address)

def get_token_decimals(token_address):
    token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    return token_contract.functions.decimals().call()

def get_token_symbol(token_address):
    token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    return token_contract.functions.symbol().call()

def format_token_amount(amount, decimals):
    return amount / (10 ** decimals)

tx_hash = '0x6a7dc8cb513254ba9d89a28d8cd5209f669b56675a434306eef9b942e898244b'
target_contract = Web3.to_checksum_address('0xBd3fa81B58Ba92a82136038B25aDec7066af3155')

tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
tx = w3.eth.get_transaction(tx_hash)
block = w3.eth.get_block(tx_receipt['blockNumber'])

print('Transaction Details:')
print('-' * 20)
print(f'From: {tx["from"]}')
print(f'Block: {tx_receipt["blockNumber"]}')
print(f'Timestamp: {datetime.utcfromtimestamp(block["timestamp"]).strftime("%Y-%m-%d %H:%M:%S UTC")}')

target_logs = [log for log in tx_receipt['logs'] if log['address'].lower() == target_contract.lower()]

for log in target_logs:
    print('\nEvent Topics:')
    print(f'Event Signature: {log["topics"][0].hex()}')
    print(f'Nonce: {int(log["topics"][1].hex(), 16)}')
    
    burn_token = decode_address(log["topics"][2])
    token_decimals = get_token_decimals(burn_token)
    token_symbol = get_token_symbol(burn_token)
    
    print(f'Burn Token: {burn_token}')
    print(f'Depositor: {decode_address(log["topics"][3])}')
    
    raw_data = log['data']
    
    amount = decode_uint256(raw_data[0:32])
    mint_recipient = decode_address(raw_data[32:64])
    destination_domain = decode_uint256(raw_data[64:96])
    destination_token_messenger = decode_address(raw_data[96:128])
    destination_caller = decode_address(raw_data[128:160])
    
    print('\nDecoded Data:')
    print(f'Amount (raw): {amount}')
    print(f'Amount ({token_symbol}): {format_token_amount(amount, token_decimals):,.2f}')
    print(f'Token Decimals: {token_decimals}')
    print(f'Mint Recipient: {mint_recipient}')
    print(f'Destination Domain: {destination_domain}')
    print(f'Destination Token Messenger: {destination_token_messenger}')
    print(f'Destination Caller: {destination_caller}')