import json
from pathlib import Path
with open(Path(__file__).parent / "transcript_full.jsonl") as f:
    for line in f:
        data = json.loads(line)
        if "tool_calls" in data:
            for tc in data["tool_calls"]:
                if tc["name"] in ["write_to_file", "replace_file_content", "multi_replace_file_content"]:
                    if tc.get("args", {}).get("TargetFile") == str(Path(__file__).parent.parent / "ai_writer.py"):
                        print(f"Found {tc['name']} at step {data.get('step_index')}")
                        if "CodeContent" in tc["args"]:
                            with open(Path(__file__).parent.parent / "ai_writer_recovered.py", "w") as out:
                                out.write(tc["args"]["CodeContent"])
