
## ACStats - Lap Time Leaderboard

ACStats is made of two components:
- A log watch python script that looks for laptimes in the output log of an Assetto Corsa server. It inserts clean laps into the SQLite database's laptimes table with driver, car, track, laptime, and timestamp.
- A Python Web App to display the data.



## Usage/Examples
After AC server (acs.exe) is started, run the log watch script. 

```python
python .\ac_server_log_watch.py

```


- Todo for custom implementation: It needs to be integratged with server start/stop batch script for a cleaner, less touch activation when changing server settings and restarting server. 

The App needs to be built which ends up being a uvicorn listener on 8080. Create a DB file so app.py can refer to it. ACstats app will initalize the database schema. Docker compose also sets up the nginx reverse proxy for socalsim.racing with Lets Encrypt Certbot.

```bash
docker-compose up --build -d
```