import sys
import os
import ai_writer

print("--- Testing OmniRoute from Firestick ---")

or_models = ["openrouter/meta-llama/llama-3.3-70b-instruct:free"]
print(f"Testing OpenRouter: {or_models}")
res1 = ai_writer._run_omniroute("Hello. Respond with exactly one word: OR_OK", omni_models=or_models)
print(f"OR Result: {res1}\n")

agy_models = ["no-think/agy/claude-sonnet-4-6"]
print(f"Testing AGY CLI: {agy_models}")
res2 = ai_writer._run_omniroute("Hello. Respond with exactly one word: AGY_OK", omni_models=agy_models)
print(f"AGY Result: {res2}")
