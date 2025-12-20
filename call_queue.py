from typing import Dict, Optional, List, Callable, Any
import datetime
import asyncio
from services.twilio import make_outbound_call
from services.gemini import GEMINI_PROMPTS

# The queue storage: {id: {call_data}}
QUEUE: Dict[int, Dict] = {}
QUEUE_CHECK_INTERVAL = 60

def get_queue() -> Dict[int, Dict]:
    """Returns the entire queue."""
    return QUEUE

def get_queued_call(queue_id: int) -> Optional[Dict]:
    """Returns a specific call by ID."""
    return QUEUE.get(queue_id)

def add_to_queue(call_data: Dict) -> int:
    """
    Adds a call to the queue, assigning the lowest available ID starting from 1.
    operating only on json as requested.
    """
    existing_ids = set(QUEUE.keys())
    new_id = 1
    while new_id in existing_ids:
        new_id += 1
    
    # Ensure the call_data matches the expected structure slightly if needed, 
    # but we just store what is passed.
    QUEUE[new_id] = call_data
    return new_id

def delete_from_queue(queue_id: int) -> bool:
    """Removes a call from the queue. Returns True if found and deleted."""
    if queue_id in QUEUE:
        del QUEUE[queue_id]
        return True
    return False

def get_due_calls() -> List[tuple[int, Dict]]:
    """
    Returns a list of (queue_id, call_data) for calls that are due.
    The expected datetime format is "YYYY-MM-DD-HH-MM".
    """
    due_calls = []
    now = datetime.datetime.now()
    
    for queue_id, call_data in QUEUE.items():
        time_str = call_data.get("datetime")
        if time_str:
            try:
                # "2025-12-20-15-30"
                scheduled_time = datetime.datetime.strptime(time_str, "%Y-%m-%d-%H-%M")
                if scheduled_time <= now:
                    due_calls.append((queue_id, call_data))
            except ValueError:
                # Malformed time, maybe ignore or log? 
                # For now let's just ignore or maybe treat as not due.
                pass
                
    return due_calls

async def process_queue_loop(get_public_url_func: Callable[[], Optional[str]], call_data_store: Dict[str, Any]):
    """Background task to process queued calls."""
    print("Started queue processing task.")
    while True:
        try:
            due_calls = get_due_calls()
            for q_id, call_data in due_calls:
                print(f"Processing queued call {q_id}")
                server_public_url = get_public_url_func()
                if server_public_url:
                    sid = make_outbound_call(server_public_url, call_data["to_number"])
                    if sid:
                         full_prompt = GEMINI_PROMPTS["outbound_init"] + call_data["prompt"]
                         call_data_store[sid] = {"prompt": full_prompt}
                         delete_from_queue(q_id)
                         print(f"Initiated queued call {q_id}, SID: {sid}")
                    else:
                        print(f"Failed to initiate queued call {q_id}")
                else:
                    print("Server public URL not set yet, skipping queue processing.")
            
            await asyncio.sleep(QUEUE_CHECK_INTERVAL)
        except Exception as e:
            print(f"Error in queue loop: {e}")
            await asyncio.sleep(QUEUE_CHECK_INTERVAL)
