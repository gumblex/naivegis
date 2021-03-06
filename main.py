#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import math
import sqlite3
import argparse

import bottle
import prcoords

app = application = bottle.default_app()

# Earth mean radius
R_EARTH = 6371000
EARTH_EQUATORIAL_RADIUS = 6378137
 
# distance between two points on a sphere
haversine = lambda lat1, lng1, lat2, lng2: 2 * R_EARTH * math.asin(
    math.sqrt(math.sin(math.radians(lat2 - lat1) / 2) ** 2 +
    math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
    math.sin(math.radians(lng2 - lng1) / 2) ** 2))

re_float = re.compile(r'^(-?[0-9]*\.?[0-9]+(e[-+]?[0-9]+)?|nan|[+-]?inf)$', re.I)

def from3857_to4326(point):
    x, y = point
    lon = math.degrees(x / EARTH_EQUATORIAL_RADIUS)
    lat = math.degrees(2 * math.atan(math.exp(y/EARTH_EQUATORIAL_RADIUS)) - math.pi/2)
    return (lat, lon)

SQLITE_FUNCTION = 31

def sql_auth(sqltype, arg1, arg2, dbname, source):
    if sqltype in (sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, SQLITE_FUNCTION):
        return sqlite3.SQLITE_OK
    else:
        return sqlite3.SQLITE_DENY

class Point(prcoords.Coords):
    pass

class DatabaseConnection:
    def __init__(self, database, readonly=True, **kwargs):
        self.conn = None

    def execute(self, sql, param=None):
        cur = self.conn.cursor()
        if param:
            cur.execute(sql, param)
        else:
            cur.execute(sql)
        return cur

class SQLite3Connection(DatabaseConnection):
    def __init__(self, database, readonly=True, cache_size='-100000', spatialite=None, **kwargs):
        self.conn = sqlite3.connect(database, **kwargs)
        if spatialite:
            self.conn.enable_load_extension(True)
            self.conn.execute("SELECT load_extension(?)", (spatialite,))
            self.conn.enable_load_extension(False)
        self.conn.create_function("geodistance", 4, haversine)
        self.conn.execute('PRAGMA cache_size=%d' % int(cache_size))
        self.conn.row_factory = sqlite3.Row
        if readonly:
            self.conn.set_authorizer(sql_auth)

class PostgreSQLConnection(DatabaseConnection):
    def __init__(self, database, readonly=True, **kwargs):
        import psycopg2, psycopg2.extras, psycopg2.extensions
        POINT = psycopg2.extensions.new_type(
                (600,), "POINT", PostgreSQLConnection.cast_point)
        psycopg2.extensions.register_type(POINT)
        self.conn = psycopg2.connect(database, cursor_factory=psycopg2.extras.DictCursor, **kwargs)
        if readonly:
            self.conn.set_session(readonly=True)
        self.conn.set_session(autocommit=True)

    @staticmethod
    def cast_point(value, cur):
        if value is None:
            return None

        # Convert from (f1, f2) syntax using a regular expression.
        m = re.match(r"\(([^)]+),([^)]+)\)", value)
        if m:
            return Point(float(m.group(1)), float(m.group(2)))
        else:
            raise psycopg2.InterfaceError("bad point representation: %r" % value)

class MSSQLConnection(DatabaseConnection):
    def __init__(self, server, user='', password='', database='', readonly=False, **kwargs):
        # readonly is not supported
        import pymssql
        self.conn = pymssql.connect(server, user, password, database, **kwargs)

    def execute(self, sql, param=None):
        cur = self.conn.cursor(as_dict=True)
        if param:
            cur.execute(sql, param)
        else:
            cur.execute(sql)
        return cur

class CSVConnection(DatabaseConnection):
    def __init__(self, database, readonly=True, header=True, spatialite=None, **kwargs):
        import csv
        class CustumDialect(csv.Dialect):
            pass
        dialect = CustumDialect
        dialect.delimiter = kwargs.get('delimiter', ',')
        dialect.doublequote = kwargs.get('doublequote', True)
        dialect.escapechar = kwargs.get('escapechar', None)
        dialect.lineterminator = kwargs.get('lineterminator', '\r\n')
        dialect.quotechar = kwargs.get('quotechar', '"')
        dialect.quoting = getattr(csv, kwargs.get('quoting', 'QUOTE_MINIMAL'))
        dialect.skipinitialspace = kwargs.get('skipinitialspace', False)
        dialect.strict = kwargs.get('strict', False)
        self.conn = sqlite3.connect(':memory:')
        if spatialite:
            self.conn.enable_load_extension(True)
            self.conn.execute("SELECT load_extension(?)", (spatialite,))
            self.conn.execute("SELECT InitSpatialMetaData()")
            self.conn.enable_load_extension(False)
        self.conn.create_function("geodistance", 4, haversine)
        self.conn.row_factory = sqlite3.Row
        try_float = lambda x: float(x) if re_float.match(x) else x
        with open(database, newline='') as f:
            reader = csv.reader(f, dialect)
            first_row = next(reader)
            if header:
                col_name = first_row
                first_row = None
            else:
                col_name = ['c%d' % (x+1) for x in range(len(first_row))]
            values = ','.join(('?',)*len(col_name))
            self.conn.execute('CREATE TABLE csv(%s)' % (','.join(col_name)))
            if first_row:
                self.conn.execute(
                    'INSERT INTO csv VALUES (%s)' % values,
                    tuple(map(try_float, first_row)))
            for row in reader:
                self.conn.execute(
                    'INSERT INTO csv VALUES (%s)' % values,
                    tuple(map(try_float, row)))
            self.conn.commit()
        if readonly:
            self.conn.set_authorizer(sql_auth)

@bottle.route('/query/', method=('POST',))
def query_api():
    q = bottle.request.forms.get('q')
    color = bottle.request.forms.get('color')
    etype = bottle.request.forms.get('type', 'marker')
    groupby = bottle.request.forms.get('groupby')
    fix = bottle.request.forms.get('fix', 'wgs')
    if not q:
        bottle.response.status = 400
        return {'error': 'empty query'}
    try:
        markers = []
        points = {}
        groups = {}
        cur = app.config['dbconn'].execute(q)
        error = None
        maxz = 0
        for i, row in enumerate(cur):
            d = dict(row)
            if 'coords' in d:
                point = d.pop('coords')
            elif fix == '3857':
                point = (d.pop('x'), d.pop('y'))
            else:
                point = (d.pop('lat'), d.pop('lon'))
            if fix == 'bd':
                lat, lon = prcoords.bd_wgs(point)
            elif fix == 'gcj':
                lat, lon = prcoords.gcj_wgs(point)
            elif fix == '3857':
                lat, lon = from3857_to4326(point)
            else:
                lat, lon = point
            d['type'] = etype
            if 'color' not in d:
                d['color'] = color
            if etype in ('marker', 'point'):
                d['pos'] = (lat, lon)
                markers.append(d)
            elif etype == 'heatmap':
                if 'z' in d:
                    z = d.pop('z')
                    maxz = max(maxz, z)
                else:
                    z = 1
                if not points:
                    points[0] = []
                    groups[0] = d
                points[0].append((lat, lon, z))
            else:
                pid = d.get(groupby, 0)
                groups[pid] = d
                if pid not in points:
                    points[pid] = []
                points[pid].append((lat, lon))
            if etype != 'heatmap' and i > app.config['maxrow']:
                error = 'only showing the first %d rows' % app.config['maxrow']
                break
        cur.close()
        if etype in ('marker', 'point'):
            return {'elements': markers, 'error': error}
        elif etype == 'heatmap':
            d = groups[0]
            d['points'] = points[0]
            d['max'] = d.get('maxz') or maxz or 1
            return {'elements': [d], 'error': error}
        else:
            elements = []
            for pid, pos in points.items():
                d = groups[pid]
                d['points'] = pos
                elements.append(d)
            return {'elements': elements, 'error': error}
    except Exception as ex:
        bottle.response.status = 500
        return {'error': '%s: %s' % (type(ex).__name__, str(ex))}


@bottle.route('/')
def index():
    return bottle.static_file('frontend.html', root=os.path.normpath(
        os.path.join(os.getcwd(), os.path.dirname(__file__))))

def main():
    parser = argparse.ArgumentParser(
        description="Such a simple and naive GIS platform.")
    parser.add_argument(
        "-l", "--listen", default='127.0.0.1', help="http server listen IP")
    parser.add_argument(
        "-p", "--port", default=6700, type=int, help="http server port")
    parser.add_argument(
        "-s", "--server", default='auto', help="bottle http server backend")
    parser.add_argument(
        "-w", "--writeable", action="store_true",
        help="disable read-only database connection (mssql doesn't support read-only)")
    parser.add_argument(
        "-t", "--type", default="sqlite3",
        choices=('sqlite3', 'pg', 'mssql', 'csv'), help="database type")
    parser.add_argument(
        "-m", "--maxrow", default=100000, type=int, help="max row number")
    parser.add_argument(
        "-c", "--config",
        help="other database parameters, format: 'a=b:c=d'. Integers, 'true', 'false' are recognized.")
    parser.add_argument("connection", nargs='+', help="database connection parameter(s)")
    args = parser.parse_args()
    kwargs = {}
    if args.config:
        for row in args.config.split(':'):
            k, v = row.split('=', 1)
            if v == 'true':
                v = True
            elif v == 'false':
                v = False
            else:
                try:
                    v = int(v)
                except ValueError:
                    pass
            kwargs[k] = v
    kwargs['readonly'] = not args.writeable
    if args.type == 'csv':
        print('Loading...')
    if args.type == 'sqlite3':
        app.config['dbconn'] = SQLite3Connection(args.connection[0], **kwargs)
    elif args.type == 'pg':
        app.config['dbconn'] = PostgreSQLConnection(' '.join(args.connection), **kwargs)
    elif args.type == 'mssql':
        app.config['dbconn'] = MSSQLConnection(*args.connection, **kwargs)
    elif args.type == 'csv':
        app.config['dbconn'] = CSVConnection(args.connection[0], **kwargs)
    app.config['maxrow'] = args.maxrow
    bottle.run(host=args.listen, port=args.port, server=args.server)

if __name__ == '__main__':
    main()
