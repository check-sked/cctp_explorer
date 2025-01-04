import aiohttp
import asyncio
import json
import csv
import random
from typing import List, Dict, Any, Optional
from datetime import datetime

DOMAIN_TO_CHAIN = {
    0: 'ethereum',
    1: 'avalanche',
    2: 'optimism',
    3: 'arbitrum',
    4: 'noble',
    5: 'solana',
    6: 'base',
    7: 'polygon',
    8: 'sui'
}

class SuiCCTPEventQuerier:
    def __init__(self):
        self.rpc_endpoint = "https://fullnode.mainnet.sui.io:443"
        self.package_id = "0x08d87d37ba49e785dde270a83f8e979605b03dc552b5548f26fdf2f49bf7ed1b"
        self.request_delay = 0.2
        self.max_retries = 5
        self.page_size = 100
        self.module_name = "receive_message"
        self.event_name = "MessageReceived"
        
    def get_retry_delay(self, attempt: int, status_code: int) -> float:
        base_delay = 1
        max_delay = 32
        delay = min(max_delay, base_delay * (2 ** attempt))
        if status_code == 429:
            delay *= 1.5
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return delay + jitter

    async def make_rpc_call(self, session: aiohttp.ClientSession, method: str, params: List[Any]) -> Dict:
        await asyncio.sleep(self.request_delay)
        
        headers = {'Content-Type': 'application/json'}
        payload = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': method,
            'params': params
        }
        
        for attempt in range(self.max_retries):
            try:
                async with session.post(self.rpc_endpoint, headers=headers, json=payload, timeout=30) as response:
                    if response.status == 200:
                        result = await response.json()
                        if 'error' in result:
                            if 'rate limit' in str(result['error']).lower():
                                delay = self.get_retry_delay(attempt, 429)
                                await asyncio.sleep(delay)
                                continue
                            raise Exception(f"RPC error: {result['error']}")
                        return result['result']
                    
                    if response.status in [429, 500, 502, 503, 504]:
                        delay = self.get_retry_delay(attempt, response.status)
                        print(f"Request failed with status {response.status}. Retrying in {delay:.2f} seconds...")
                        await asyncio.sleep(delay)
                        continue
                    
                    raise Exception(f"RPC call failed with status code: {response.status}")
                    
            except Exception as e:
                delay = self.get_retry_delay(attempt, 0)
                print(f"Error: {str(e)}. Retrying in {delay:.2f} seconds...")
                await asyncio.sleep(delay)
                continue
        
        raise Exception(f"Max retries exceeded for method {method}")

    async def get_transaction(self, session: aiohttp.ClientSession, digest: str) -> Dict:
        return await self.make_rpc_call(
            session, 
            'sui_getTransactionBlock',
            [digest, {
                'showInput': True,
                'showEffects': True,
                'showEvents': True,
                'showBalanceChanges': True,
                'showObjectChanges': True
            }]
        )

    async def get_checkpoint_for_tx(self, session: aiohttp.ClientSession, tx_digest: str) -> int:
        result = await self.make_rpc_call(
            session,
            'sui_getTransactionBlock',
            [tx_digest, {
                'options': {
                    'showInput': False,
                    'showRawInput': False,
                    'showEffects': False,
                    'showEvents': False,
                    'showObjectChanges': False,
                    'showBalanceChanges': False,
                    'showType': False
                }
            }]
        )
        return int(result.get('checkpoint', 0))

    async def query_events(
        self,
        session: aiohttp.ClientSession,
        cursor: Optional[Dict] = None
    ) -> Dict:
        module_and_event = f"{self.package_id}::{self.module_name}::{self.event_name}"
        event_filter = {
            "MoveEventType": module_and_event
        }
        
        query_params = [
            event_filter,
            cursor,
            self.page_size,
            True  # descending
        ]
        
        return await self.make_rpc_call(session, 'suix_queryEvents', query_params)

    def process_event_and_tx(self, event: Dict, tx: Dict, checkpoint: int) -> Dict[str, Any]:
        event_data = event.get('parsedJson', {})
        source_domain = event_data.get('source_domain')
        source_chain = DOMAIN_TO_CHAIN.get(source_domain, f"unknown_{source_domain}")

        usdc_amount = None
        for change in tx.get('balanceChanges', []):
            if 'usdc' in change.get('coinType', '').lower():
                usdc_amount = int(change['amount']) / 1e6
                break

        timestamp_ms = event.get('timestampMs', '0')
        
        transfer_data = {
            'digest': tx['digest'],
            'sender': event.get('sender'),
            'checkpoint': checkpoint,
            'checkpoint_timestamp': datetime.fromtimestamp(int(timestamp_ms)/1000).isoformat(),
            'nonce': event_data.get('nonce'),
            'source_chain': source_chain,
            'usdc_amount': usdc_amount,
            'sender_address': event_data.get('sender')
        }

        return transfer_data

    async def query_cctp_transfers(self, limit: Optional[int] = None, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            all_transfers = []
            cursor = None
            page = 1
            
            while True:
                try:
                    print(f"\nFetching page {page} of events...")
                    result = await self.query_events(session, cursor)
                    
                    events = result.get('data', [])
                    if not events:
                        print("No more events found.")
                        break
                    
                    print(f"Processing {len(events)} events from page {page}")
                    
                    for event in events:
                        try:
                            tx_digest = event.get('id', {}).get('txDigest')
                            if not tx_digest:
                                print(f"Could not find transaction digest in event")
                                continue
                            
                            tx = await self.get_transaction(session, tx_digest)
                            checkpoint = await self.get_checkpoint_for_tx(session, tx_digest)
                            
                            transfer = self.process_event_and_tx(event, tx, checkpoint)
                            all_transfers.append(transfer)
                            print(f"Processed transfer: {transfer['digest']} - Amount: {transfer['usdc_amount']} USDC from {transfer['source_chain']} at checkpoint {checkpoint}")
                        except Exception as e:
                            print(f"Error processing event: {e}")
                    
                    if limit and len(all_transfers) >= limit:
                        all_transfers = all_transfers[:limit]
                        break

                    if max_pages and page >= max_pages:
                        print(f"Reached maximum page limit of {max_pages}")
                        break
                    
                    cursor = result.get('nextCursor')
                    if not cursor:
                        print("No more pages available.")
                        break
                    
                    page += 1
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"Error fetching page {page}: {e}")
                    break
            
            return all_transfers

async def main():
    querier = SuiCCTPEventQuerier()
    
    try:
        print("Starting query for CCTP transfers...")
        transfers = await querier.query_cctp_transfers(limit=None, max_pages=2)  # Only fetch 2 pages
        
        if not transfers:
            print("No transfers found!")
            return
            
        csv_filename = 'sui_transfers_in.csv'
        csv_fields = ['digest', 'checkpoint', 'checkpoint_timestamp', 'nonce', 'sender', 'source_chain', 'usdc_amount', 'sender_address']
        
        with open(csv_filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            for transfer in sorted(transfers, key=lambda x: int(x['checkpoint'])):
                csv_row = {field: transfer[field] for field in csv_fields}
                writer.writerow(csv_row)
        
        print(f"\nQuery complete! Found {len(transfers)} total CCTP transfers")
        print(f"Results saved to {csv_filename}")
        
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())