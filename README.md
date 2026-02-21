# DASHBOARD INSTRUCTIONS
Dashboard project to view summary and information on a chosen list of company tickers

Requirements:
In terminal/cmd/powershell, set current directory to the folder containing the project (cd 'project folder path'), then run (pip install -r requirements.txt). This should install all necessary modules, if you run into any issues in the running of scripts just install the library terminal tells you to (e.g. pip install pandas). 

Tickers naming convention:
To choose tickers to load into dashboard for selection, modify the tickers list in the TA.py file. Tickers may require a specific suffix after if they belong to different exchanges. The yahoo finance module likely sets US stocks to standard. An example of this is for tickers on the London stock exchange, which requires the .L suffix (e.g. PRE.L, SML.L).

API keys:
API Keys are stored in the .env file. This has been left empty in this repository. Please enter your own API key into this file. (open as txt file/notebook, and simply add your key into the empty space). If using gemini, which is currently the only working LLM for this, you will need to generate an API key then set up billing, even to use the free tier. 

Running the dashboard:
Open dashpy.py either via cmd, powershell or whatever python editor you prefer. When you run the file, the terminal will return all outputs. Scroll through and look for an server address (should look like http://127.0.0.1:8050/, this means the server is local to your machine). CTRL + click that link, or copy paste, to open in browser.
