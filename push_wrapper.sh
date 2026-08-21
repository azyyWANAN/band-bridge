#!/data/data/com.termux/files/usr/bin/bash
source ~/.bashrc 2>/dev/null
cd ~
echo "=== $(date '+%F %T') ===" >> ~/push.log 2>&1
python push.py >> ~/push.log 2>&1
echo "exit: $?" >> ~/push.log 2>&1
