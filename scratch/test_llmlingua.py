import time
print("Importing llmlingua...")
start = time.time()
from llmlingua import PromptCompressor
print(f"Imported in {time.time() - start:.2f}s")

print("Initializing PromptCompressor...")
start = time.time()
# Use LLMLingua-2 model as specified in the logs
compressor = PromptCompressor(
    model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
    use_llmlingua2=True,
    device_map="cpu"
)
print(f"Initialized in {time.time() - start:.2f}s")

text = "This is a very long text that we want to compress using LLMLingua to see if it works correctly and saves tokens in the process." * 10
print(f"Original text word count: {len(text.split())}")
start = time.time()
res = compressor.compress_prompt(text, rate=0.5)
print(f"Compressed in {time.time() - start:.2f}s")
print("Result:", res)
