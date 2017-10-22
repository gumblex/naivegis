# Naïve GIS
Such a simple and naive GIS platform.

Fuck those slow, complicated, expensive and "user-friendly" GIS software. I just want to show some points on the map.

## Usage

```
usage: main.py [-h] [-l LISTEN] [-p PORT] [-s SERVER] [-w]
               [-t {sqlite3,pg,mssql,csv}] [-m MAXROW] [-c CONFIG]
               connection [connection ...]

Such a simple and naive GIS platform.

positional arguments:
  connection            database connection parameter(s)

optional arguments:
  -h, --help            show this help message and exit
  -l LISTEN, --listen LISTEN
                        http server listen IP
  -p PORT, --port PORT  http server port
  -s SERVER, --server SERVER
                        bottle http server backend
  -w, --writeable       disable read-only database connection (mssql doesn't
                        support read-only)
  -t {sqlite3,pg,mssql,csv}, --type {sqlite3,pg,mssql,csv}
                        database type
  -m MAXROW, --maxrow MAXROW
                        max row number
  -c CONFIG, --config CONFIG
                        other database parameters, format: 'a=b:c=d'.
                        Integers, 'true', 'false' are recognized.
```

* **sqlite3**: `connection` is the filename. Has an option `cache_size`, defaults to -100000. Other -c options see [here](https://docs.python.org/3/library/sqlite3.html#sqlite3.connect).
* **pg**: Needs `psycopg2` library. `connection` is the [connection string](https://www.postgresql.org/docs/current/static/libpq-connect.html#libpq-connstring). Other -c options see the docs mentioned before.
* **mssql**: Needs `pymssql` library. `connection` is (server, user, password, database) five arguments. Doesn't support read-only connection. Other -c options see [here](http://pymssql.org/en/stable/ref/pymssql.html#pymssql.connect).
* **csv**: `connection` is the file name. The csv file is read into an in-memory SQLite database, where the table name is `csv`. -w means writeable to this memory database. Has an option `header`, to specify whether the csv file has a header. If there is no header, the column names will be c1, c2, etc. Other -c options see [here](https://docs.python.org/3/library/csv.html#dialects-and-formatting-parameters).

In the web interface, type in your SQL query. Columns named `lat`, `lon` specifies the location. (Except for the EPSG:3857 coordinate system, they should be `x` and `y`.) There are other optional columns to change display: `color` (element color), `title` (marker title), `alt` (marker alt), `text` (marker popup text), `weight` (polyline/polygon stroke width), `opacity` (point fill opacity, polyline/polygon stroke opacity), `radius` (point, heatmap), `blur` (heatmap), `minOpacity` (heatmap).

Then, set element color (except for heatmap) and element type. The "Coords" sets which kind of coordinates that the data uses. If "Reset" is checked, the canvas will be reset on next query. Every query results add up until reset.
