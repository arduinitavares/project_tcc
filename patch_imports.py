import re
with open('api.py', 'r') as f:
    content = f.read()

# Fix duplicate Task import
content = content.replace('    TaskExecutionLog,\n    Task,\n    TaskStatus,', '    TaskExecutionLog,\n    TaskStatus,')
content = content.replace('from agile_sqlmodel import (', 'from agile_sqlmodel import (')

with open('api.py', 'w') as f:
    f.write(content)
