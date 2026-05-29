#!/bin/bash
cd "$(dirname "$0")"
echo "Starting XO Marriage Podcast Dashboard..."
echo "Open http://localhost:8501 in your browser"
python3 -m streamlit run dashboard.py --server.port 8501
