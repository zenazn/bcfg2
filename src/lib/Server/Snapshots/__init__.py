__all__ = ['models', 'db_from_config', 'setup_session']

import sqlalchemy, sqlalchemy.orm, ConfigParser

def db_from_config(fname='/etc/bcfg2.conf'):
    cp = ConfigParser.ConfigParser()
    cp.read([fname])
    driver = cp.get('snapshots', 'driver')
    if driver == 'sqlite':
        path = cp.get('snapshots', 'database')
        return 'sqlite:///%s' % path
    elif driver in ['mysql', 'postgres']:
        user = cp.get('snapshots', 'user')
        password = cp.get('snapshots', 'password')
        host = cp.get('snapshots', 'host')
        db = cp.get('snapshots', 'database')
        return '%s://%s:%s@%s/@s' % (driver, user, password, host, db)
    else:
        raise Exception, "unsupported db driver %s" % driver


def setup_session(debug=False):
    engine = sqlalchemy.create_engine(db_from_config(),
                                      echo=debug)
    Session = sqlalchemy.orm.sessionmaker()
    Session.configure(bind=engine)
    return Session()
