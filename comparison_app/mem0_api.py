# Step 1 — Install the SDK. Run this in your terminal (not in Python):
#
#     pip install mem0ai
#
# Step 2 — Save this file as mem0_quickstart.py and run: python mem0_quickstart.py
import os
from mem0 import MemoryClient

# Set your API key (get one at https://app.mem0.ai)
client = MemoryClient(api_key=os.getenv("MEM0_API_KEY", "your-api-key-here"))

# Use the same user ID when adding and searching
USER_ID = "user123"

# Add a memory
messages = [
    {"role": "user", "content": "I'm a vegetarian and allergic to nuts."},
    {"role": "assistant", "content": "Got it! I'll remember your dietary preferences."},
]
client.add(messages, user_id=USER_ID)

# Search memories
results = client.search(
    "What are my dietary restrictions?",
    filters={"user_id": USER_ID}
)
print(results)