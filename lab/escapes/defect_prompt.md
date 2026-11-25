# Role
You are building an evaluation set for code reviewers. Below is a SPEC and the CORRECT, accepted change (DIFF) that implements it.
The files in your current directory are the repository AFTER this correct change.

# Task
Introduce exactly ONE realistic defect of class {CLASS}: {CLASS_DESC}
- Edit only these files (product code, never tests): 
{FILES}
- Change at most 30 lines in total. Keep the code compiling/importable and keep the style of the surrounding code.
- The defect must violate the SPEC or break existing behaviour in a way a careful reviewer who reads the SPEC and the full diff
  could find and explain. It must not be a pure refactor or a behaviour-equivalent rewrite.
- Do not add comments, TODOs or names that reveal the defect. Do not touch any test file. Do not run the tests.
- Prefer a defect that the existing tests might not catch.

# Output
After editing, reply with a single JSON object on its own line, nothing after it:
{"file": "<edited file path>", "answer_key": "<one Turkish sentence: what is wrong and which SPEC rule or existing behaviour it breaks>"}

# SPEC
{SPEC}

# CORRECT DIFF
{DIFF}
