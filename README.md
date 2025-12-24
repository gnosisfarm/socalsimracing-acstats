ACStats is two components. A log scraper python script and a python Web App.
Simple log scraper that looks for laptimes in the output.log of an Assetto Corsa server. It inserts clean laps into the SQLite database's laptimes table with driver, car, track, laptime, and timestamp. 


After running AC server, run the log scraper. It needs to be integratged with server start/stop for a cleaner, less touch activation.
The App needs to be built which ends up being a uvicorn listener on 8080.
Create a DB file so app.py can refer to it. 
ACstats app will initalize the database schema. 
Docker compose also sets up the nginx reverse proxy for socalsim.racing with Lets Encrypt Certbot. 
