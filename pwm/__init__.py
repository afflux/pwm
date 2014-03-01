import base64
import getpass
import hashlib
import requests
import os
import sys
import textwrap
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from logging import getLogger

from . import encoding

try:
    from configparser import RawConfigParser
except:
    # python 2
    from ConfigParser import RawConfigParser
    input = raw_input


Base = declarative_base()
_logger = getLogger('pwm')


class Domain(Base):
    __tablename__ = 'domain'
    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String(30))
    salt = sa.Column(sa.String(128))
    charset = sa.Column(sa.String(128))
    encoding_length = sa.Column(sa.Integer())


    def __init__(self, **kwargs):
        super(Domain, self).__init__(**kwargs)
        if not 'encoding_length' in kwargs:
            self.encoding_length = encoding.DEFAULT_LENGTH
        if not 'charset' in kwargs:
            self.charset = encoding.DEFAULT_ALPHABET
        if not 'salt' in kwargs:
            self.new_salt()


    def new_salt(self):
        self.salt = base64.b64encode(os.urandom(32))


    def derive_key(self, master_password):
        encoder = encoding.Encoder(self.charset)
        bytes = ('%s:%s:%s' % (master_password, self.name, self.salt)).encode('utf8')
        return encoder.encode(hashlib.sha1(bytes), self.encoding_length)


    def __repr__(self):
        return 'Domain(name=%s, salt=%s, charset=%s, length=%s)' \
                % (self.name, self.salt, self.charset, self.encoding_length)


def search(args):
    pwm = PWM(config_file=args.config_file)
    results = pwm.search(args.query)
    for result in results:
        print(result.name)


def get(args):
    pwm = PWM(config_file=args.config_file)
    charset = encoding.lookup_alphabet(args.charset)
    domain = pwm.get_domain(args.domain, args.length, charset)
    master_password = getpass.getpass('Enter your master password: ')
    print(domain.derive_key(master_password))


def set(args):
    pwm = PWM(config_file=args.config_file)



class PWM(object):

    def __init__(self, config_file=None, session=None):
        if not os.path.exists(config_file):
            if not os.path.exists(os.path.dirname(config_file)):
                os.makedirs(os.path.dirname(config_file))
            self.run_setup(config_file)
        self.read_config(config_file)
        self.session = session


    def read_config(self, config_file):
        defaults = {
            'server-certificate': None,
            'client-certificate': None,
            'client-key': None,
        }
        config_parser = RawConfigParser(defaults=defaults)
        config = {}
        config_parser.read(config_file)
        config['database'] = config_parser.get('pwm', 'database')

        client_certificate = config_parser.get('pwm', 'client-certificate')
        client_key = config_parser.get('pwm', 'client-key')
        if client_certificate and client_key:
            client_certificate_path = os.path.join(os.path.dirname(config_file), client_certificate)
            client_key_path = os.path.join(os.path.dirname(config_file), client_key)
            config['auth'] = (client_certificate_path, client_key_path)

        if config_parser.get('pwm', 'server-certificate'):
            config['server_certificate'] = os.path.join(os.path.dirname(config_file), config_parser.get('pwm', 'server-certificate'))
        self.config = config


    def search(self, query):
        if not self.session:
            self.init_db_session()
        results = self.session.query(Domain).filter(Domain.name.ilike('%%%s%%' % query)).all()
        return results


    def run_setup(self, config_file):
        print(textwrap.dedent("""\
            Hi, it looks like it's the first time you're using pwm on this machine. Let's take a little
            moment to set things up before we begin."""))
        db_uri = input('Which database do you want to use (default: local sqlite at ~/.pwm/db.sqlite) ').strip() or 'local'
        rc_dir = os.path.dirname(config_file)

        if db_uri == 'local':

            # normalize windows-style paths for sqlalchemy:
            rc_dir = rc_dir.replace('\\', '/')

            # Create the local database
            db_uri = 'sqlite:///%s/db.sqlite' % rc_dir
        if not '://' in db_uri:
            # Not a sqlalchemy-compatible connection string or https URI, assume it's a local path and make a sqlite
            # uri out of it
            db_uri = 'sqlite:///%s' % db_uri
        if not (db_uri.startswith('https:') or db_uri.startswith('http:')):
            # It's a local db, make sure our tables exist
            db = sa.create_engine(db_uri)
            Base.metadata.create_all(db)

        config_parser = RawConfigParser()
        config_parser.add_section('pwm')
        config_parser.set('pwm', 'database', db_uri)

        with open(config_file, 'w') as config_file_fh:
            config_parser.write(config_file_fh)


    def get_domain(self, domain, length=encoding.DEFAULT_LENGTH,
    charset=encoding.DEFAULT_ALPHABET):
        protocol = self.config['database'].split(':', 1)[0]
        if protocol in ('https', 'http'):
            return self.get_domain_from_rest_api(domain, length, charset)
        else:
            return self.get_domain_from_db(domain, length, charset)


    def get_domain_from_rest_api(self, domain, length, charset):
        request_args = {
            'params': {'domain': domain}
        }
        verify = True
        server_certificate = self.config.get('server_certificate')
        if server_certificate:
            verify = os.path.join(os.path.dirname(server_certificate), server_certificate)
            _logger.debug('Pinning server with certificate at %s', verify)

        # Test for SNI support on python 2
        if sys.version_info < (3, 0, 0):
            try:
                import urllib3.contrib.pyopenssl
                urllib3.contrib.pyopenssl.inject_into_urllib3()
            except ImportError:
                _logger.warning("Running on python 2 without SNI support, can't verify server certificates.")
                verify = False
        request_args['verify'] = verify

        if self.config.get('auth'):
            request_args['cert'] = self.config['auth']
        response = requests.get(self.config['database'] + '/get', **request_args)
        domain = Domain(name=domain, salt=response.json()['salt'])
        return domain


    def get_domain_from_db(self, domain, length, charset):
        if not self.session:
            self.init_db_session()
        domain = self.get_or_insert_domain(self.session, domain, length,
                                         charset)
        return domain


    def get_or_insert_domain(self, session, domain_name, length, charset):
        domain = session.query(Domain).filter(Domain.name == domain_name).first()
        if domain is None:
            domain = Domain(name=domain_name, encoding_length=length,
                            charset=charset)
            session.add(domain)
            session.commit()
        return domain


    def init_db_session(self):
        db = sa.create_engine(self.config['database'])
        DBSession = sessionmaker(bind=db)
        self.session = DBSession()
