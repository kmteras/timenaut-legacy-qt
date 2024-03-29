import logging
from datetime import date, datetime, timedelta
from datetime import time as timetime
from time import time
from typing import List, Tuple, Dict, Union

import PySide2.QtSql as QtSql

from timechart.core.models.process import Process
from timechart.core.models.process_heartbeat import ProcessHeartbeat
from timechart.core.models.window import Window
from timechart.core.settings import Settings
from timechart.util.database_error import DatabaseError
from timechart.util.util import get_data_file_location


def connect() -> None:
    db = QtSql.QSqlDatabase.addDatabase("QSQLITE")
    db.setDatabaseName(get_data_file_location())

    if not db.open():
        raise DatabaseError("Could not open database!")

    logging.info(f"Connected to database {get_data_file_location()}")
    try:
        create_tables()
    except DatabaseError as e:
        logging.error(e)
        raise DatabaseError("Error creating tables")


def create_tables() -> None:
    query = QtSql.QSqlQuery()
    if not query.exec_("PRAGMA foreign_keys = ON;"):
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS processes("
                       "id INTEGER PRIMARY KEY, "
                       "path TEXT,"  # text may be NULL because of Wayland sloppy support
                       "type_str TEXT,"
                       "FOREIGN KEY (type_str) REFERENCES productivity_type(type));"):
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS windows("
                       "id INTEGER PRIMARY KEY, "
                       "process_id INTEGER NOT NULL, "
                       "title TEXT NOT NULL,"
                       "type_str TEXT DEFAULT NULL,"
                       "FOREIGN KEY (process_id) REFERENCES processes(id),"
                       "FOREIGN KEY (type_str) REFERENCES productivity_type(type));"):
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS heartbeats("
                       "process_id INTEGER NOT NULL,"
                       "window_id INTEGER NOT NULL,"
                       "start_time INTEGER NOT NULL,"
                       "end_time INTEGER NOT NULL,"
                       "idle BOOLEAN DEFAULT FALSE NOT NULL,"
                       "FOREIGN KEY (process_id) REFERENCES processes(id), "
                       "FOREIGN KEY (window_id) REFERENCES windows(id));"):
        raise DatabaseError(query.lastError())

    if not query.exec_("CREATE TABLE IF NOT EXISTS productivity_type("
                       "type TEXT NOT NULL, "
                       "color TEXT NOT NULL,"
                       "removable BOOLEAN DEFAULT TRUE,"
                       "UNIQUE(type));"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('unknown', '#808585', 'false')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('work', '#84ba5b', 'false')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('unproductive', '#d35e60', 'false')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('games', '#9067a7', 'false')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('social', '#7293cb', 'false')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('social', '#7293cb', 'false')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('misc', '#82cfa5', 'true')"):
        raise DatabaseError(query.lastError())

    if not query.exec_("INSERT OR REPLACE INTO productivity_type VALUES ('new', '#717e91', 'false')"):
        raise DatabaseError(query.lastError())

    logging.info("Created database tables")


def add_process(process: Process) -> int:
    query = QtSql.QSqlQuery()

    # Check if the process already exists in the database
    query.prepare("SELECT * FROM processes WHERE path = :path")
    query.bindValue(":path", process.path)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        # If the process already exists
        if query.next():
            return query.value(0)

    query.prepare("INSERT INTO processes (path, type_str) VALUES (:path, :type)")
    query.bindValue(":path", process.path)
    query.bindValue(":type", 'unknown')
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        return query.lastInsertId()


def add_window(window: Window, process_id: int) -> int:
    query = QtSql.QSqlQuery()

    # Check if the window already exists in the database
    query.prepare("SELECT * FROM windows WHERE title = :title")
    query.bindValue(":title", window.title)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        # If the window already exists
        if query.next():
            return query.value(0)

    query.prepare("INSERT INTO windows (title, process_id) VALUES (:title, :process_id)")
    query.bindValue(":title", window.title)
    query.bindValue(":process_id", process_id)
    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        return query.lastInsertId()


# TODO: put into class?
last_process_id = None
last_window_id = None
last_start_time = time()
last_end_time = time()
last_idle = False


def add_heartbeat(heartbeat: ProcessHeartbeat) -> None:
    global last_process_id
    global last_window_id
    global last_start_time
    global last_end_time
    global last_idle

    if not heartbeat.is_valid():
        return

    process_id = add_process(heartbeat.process)
    window_id = add_window(heartbeat.window, process_id)
    end_time = int(heartbeat.time)

    if process_id == last_process_id and window_id == last_window_id and last_idle == heartbeat.idle:
        query = QtSql.QSqlQuery()
        query.prepare(
            "UPDATE heartbeats "
            "SET end_time=:end_time "
            "WHERE start_time=:last_start_time")

        end_time = min(int(last_end_time) + Settings().heartbeat_time, end_time)

        query.bindValue(":last_start_time", last_start_time)
        query.bindValue(":end_time", end_time)
        last_end_time = end_time
        if not query.exec_():
            raise DatabaseError(query.lastError())
    else:
        if last_window_id is not None:
            # Update the end time of the last process
            query = QtSql.QSqlQuery()
            query.prepare(
                "UPDATE heartbeats "
                "SET end_time=:end_time "
                "WHERE start_time=:last_start_time")

            limited_end_time = min(int(last_end_time) + Settings().heartbeat_time, end_time)

            query.bindValue(":last_start_time", last_start_time)
            query.bindValue(":end_time", limited_end_time)
            if not query.exec_():
                raise DatabaseError(query.lastError())

        # Add new process
        query = QtSql.QSqlQuery()
        query.prepare(
            "INSERT INTO heartbeats (process_id, window_id, start_time, end_time, idle) "
            "VALUES (:process_id, :window_id, :datetime, :datetime, :idle)")
        query.bindValue(":process_id", process_id)
        query.bindValue(":window_id", window_id)
        query.bindValue(":datetime", end_time)
        query.bindValue(":idle", heartbeat.idle)
        if not query.exec_():
            raise DatabaseError(query.lastError())

        last_process_id = process_id
        last_window_id = window_id
        last_start_time = int(heartbeat.time)
        last_end_time = heartbeat.time
        last_idle = heartbeat.idle


def get_window_data() -> List[Tuple[Process, Window, int]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT
            path,
            title,
            SUM(difference) AS total_time,
            CASE
                WHEN w.type_str IS NULL
                    THEN p.type_str
                ELSE w.type_str
            END,
            CASE
                WHEN w.type_str IS NULL
                    THEN pt.color
                ELSE wt.color
            END
        FROM heartbeats AS hb
        JOIN
            (SELECT start_time, end_time - start_time AS difference FROM heartbeats) d
        ON d.start_time=hb.start_time
        LEFT JOIN processes p on hb.process_id = p.id
        LEFT JOIN windows w on hb.window_id = w.id
        LEFT JOIN productivity_type pt on p.type_str = pt.type
        LEFT JOIN productivity_type wt on w.type_str = wt.type
        WHERE hb.idle = FALSE
        GROUP BY hb.process_id, window_id
        HAVING
            total_time > 0
        ORDER BY SUM(difference) DESC
        """
    )

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            process = Process(query.value(0))
            window = Window(query.value(1), type_str=query.value(3), type_color=query.value(4))
            count = query.value(2)
            results.append((process, window, count))

    return results


def get_window_data_by_process(process_id: int) -> List[Tuple[Window, int]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT 
            window_id, 
            title, 
            SUM(difference) AS total_time,
            CASE
                WHEN w.type_str IS NULL
                    THEN p.type_str
                ELSE w.type_str
            END,
            CASE
                WHEN w.type_str IS NULL
                    THEN pt.color
                ELSE wt.color
            END
        FROM heartbeats AS hb
        JOIN 
            (SELECT start_time, end_time - start_time AS difference FROM heartbeats) d 
        ON d.start_time=hb.start_time
        LEFT JOIN windows w ON hb.window_id = w.id
        LEFT JOIN processes p ON p.id = w.process_id
        LEFT JOIN productivity_type pt on p.type_str = pt.type
        LEFT JOIN productivity_type wt on w.type_str = wt.type
        WHERE w.process_id=:process_id AND hb.idle = FALSE
        GROUP BY hb.process_id, window_id
        HAVING 
            total_time > 0
        ORDER BY SUM(difference) DESC
        """
    )

    query.bindValue(":process_id", process_id)

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            window = Window(
                query.value(1),
                window_id=query.value(0),
                type_str=query.value(3),
                type_color=query.value(4))
            count = query.value(2)
            results.append((window, count))

    return results


def get_process_data() -> List[Tuple[Process, int]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT 
            path, 
            SUM(difference), 
            process_id,
            pt.type,
            pt.color
        FROM heartbeats AS hb
        JOIN 
            (SELECT 
                start_time, 
                end_time - start_time AS difference 
            FROM 
                heartbeats) d 
        ON 
            d.start_time=hb.start_time
        LEFT JOIN 
            processes p on hb.process_id = p.id
        LEFT JOIN 
            productivity_type pt on p.type_str = pt.type
        WHERE hb.idle = FALSE
        GROUP BY 
            process_id
        ORDER BY 
            SUM(difference) DESC
        """
    )

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            process = Process(
                query.value(0),
                process_id=query.value(2),
                type_str=query.value(3),
                type_color=query.value(4))
            count = query.value(1)
            results.append((process, count))

    return results


def get_types() -> List:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT
            type,
            color,
            removable
        FROM productivity_type
        ORDER BY (CASE WHEN type = 'new' THEN 1 ELSE 0 END), removable
        """
    )

    types = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            type_name = query.value(0)
            color = query.value(1)
            removable = query.value(2)
            types.append((type_name, color, removable))

    return types


def set_window_type(window_id: int, type_str: str) -> None:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        UPDATE
            windows
        SET
            type_str=:type_str
        WHERE windows.id = :window_id
        """
    )

    if type_str == "unknown":
        type_str = None

    query.bindValue(":type_str", type_str)
    query.bindValue(":window_id", window_id)

    if not query.exec_():
        raise DatabaseError(query.lastError())


def set_process_type(process_id: int, type_str: str) -> None:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        UPDATE
            processes
        SET
            type_str=:type_str
        WHERE processes.id = :process_id
        """
    )

    query.bindValue(":type_str", type_str)
    query.bindValue(":process_id", process_id)

    if not query.exec_():
        raise DatabaseError(query.lastError())


def get_timeline_data() -> List:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
SELECT
    CASE
        WHEN w.type_str IS NULL
            THEN p.type_str
        ELSE w.type_str
    END AS type_,
    SUM(hb.end_time - hb.start_time) AS spent_time,
    datetime(ROUND(hb.start_time / (60 * 10), 0) * (60 * 10), 'unixepoch', 'localtime') AS timeframe,
    CASE
        WHEN w.type_str IS NULL
            THEN pt.color
        ELSE wt.color
    END AS type_color
FROM
    heartbeats AS hb
LEFT JOIN
    windows w ON hb.window_id = w.id
LEFT JOIN
    processes p ON p.id = w.process_id
LEFT JOIN
    productivity_type pt on p.type_str = pt.type
LEFT JOIN
    productivity_type wt on w.type_str = wt.type
WHERE
    hb.idle = FALSE
GROUP BY
    ROUND(hb.start_time / (60 * 10), 0) * (60 * 10),
    type_
        """
    )

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            type_ = query.value(0)
            spent_time = query.value(1)
            timeframe = query.value(2)
            type_color = query.value(3)
            results.append({'type': type_, 'duration': int(spent_time), 'date_time': timeframe, 'color': type_color})
    return results


def get_type_data(date_=None) -> List[Dict[str, Union[str, int]]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        SELECT
            SUM(difference),
            CASE
                WHEN w.type_str IS NULL
                    THEN p.type_str
                ELSE w.type_str
            END AS type_wp,
            CASE
                WHEN w.type_str IS NULL
                    THEN pt.color
                ELSE wt.color
            END AS type_color
        FROM heartbeats AS hb
        JOIN
            (SELECT
                start_time,
                end_time - start_time AS difference
            FROM
                heartbeats) d
        ON
            d.start_time=hb.start_time
        LEFT JOIN windows w ON hb.window_id = w.id
        LEFT JOIN processes p ON p.id = w.process_id
        LEFT JOIN productivity_type pt on p.type_str = pt.type
        LEFT JOIN productivity_type wt on w.type_str = wt.type
        WHERE 
            d.start_time > :startDate AND d.start_time < :endDate AND hb.idle = FALSE
        GROUP BY
            type_wp
        ORDER BY
            SUM(difference) DESC
        """
    )

    if date is not None:
        query.bindValue(":startDate", int(datetime.combine(date=date_, time=timetime.min).timestamp()))
        query.bindValue(":endDate",
                        int(datetime.combine(date=date_ + timedelta(days=1), time=timetime.min).timestamp()))
    else:
        query.bindValue(":startDate", 0)
        query.bindValue(":endDate", 2 ** 32)

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            results.append({
                "count": query.value(0),
                "type": query.value(1),
                "color": query.value(2)})

    return results


def get_process_data_type(date_=None) -> List[Tuple[Process, int]]:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
SELECT
    path,
    SUM(hb.end_time - hb.start_time),
    hb.process_id,
    CASE
        WHEN w.type_str IS NULL
            THEN p.type_str
        ELSE w.type_str
    END AS type_,
    CASE
        WHEN w.type_str IS NULL
            THEN pt.color
        ELSE wt.color
    END AS type_color
FROM heartbeats AS hb
LEFT JOIN
    processes p on hb.process_id = p.id
LEFT JOIN
    windows w ON hb.window_id = w.id
LEFT JOIN
    productivity_type pt on p.type_str = pt.type
LEFT JOIN
    productivity_type wt on w.type_str = wt.type
WHERE hb.start_time > :startDate AND hb.start_time < :endDate AND hb.idle = FALSE
GROUP BY
    type_, hb.process_id
ORDER BY
    SUM(hb.end_time - hb.start_time) DESC
        """
    )

    if date is not None:
        query.bindValue(":startDate", int(datetime.combine(date=date_, time=timetime.min).timestamp()))
        query.bindValue(":endDate",
                        int(datetime.combine(date=date_ + timedelta(days=1), time=timetime.min).timestamp()))
    else:
        query.bindValue(":startDate", 0)
        query.bindValue(":endDate", 2 ** 32)

    results = []

    if not query.exec_():
        raise DatabaseError(query.lastError())
    else:
        while query.next():
            process = Process(
                query.value(0),
                process_id=query.value(2),
                type_str=query.value(3),
                type_color=query.value(4))
            count = query.value(1)
            results.append((process, count))

    return results

def delete_process_references(type_str: str) -> None:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        UPDATE processes SET type_str = 'unknown' WHERE type_str =:type_str;
        """
    )

    query.bindValue(":type_str", type_str)

    if not query.exec_():
        raise DatabaseError(query.lastError())

def delete_window_references(type_str: str) -> None:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        UPDATE windows AS win
        SET type_str = (SELECT type_str FROM processes WHERE processes.id = win.process_id)
        WHERE win.type_str =:type_str
        """
    )

    query.bindValue(":type_str", type_str)

    if not query.exec_():
        raise DatabaseError(query.lastError())

def delete_type(type_str: str) -> None:
    query = QtSql.QSqlQuery()

    query.prepare(
        """
        DELETE FROM productivity_type WHERE type=:type_str;
        """
    )

    query.bindValue(":type_str", type_str)
    query.bindValue(":removable_bool", True)

    delete_process_references(type_str)
    delete_window_references(type_str)
    if not query.exec_():
        raise DatabaseError(query.lastError())


def add_type(type_str: str) -> None:
    query = QtSql.QSqlQuery()

    import random
    r = lambda: random.randint(0, 255)
    color = '#%02X%02X%02X' % (r(), r(), r())

    query.prepare(
        """
        INSERT OR REPLACE INTO productivity_type VALUES (:type_str, :color, 'true');
        """
    )

    query.bindValue(":type_str", type_str)
    query.bindValue(":color", color)

    if not query.exec_():
        raise DatabaseError(query.lastError())
