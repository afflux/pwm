from pwm import Domain, PWM, DuplicateDomainException, NotReadyException
from pwm.core import Base

import os
import tempfile
import unittest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker


class PWMCoreTest(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(delete=False)
        self.tmp_db.close()
        db = sa.create_engine('sqlite:///%s' % self.tmp_db.name)
        Base.metadata.create_all(db)
        DBSession = sessionmaker(bind=db)
        self.session = DBSession()
        self.session.add(Domain(name='example.com', salt='NaCl'))
        self.session.add(Domain(name='otherexample.com', salt='supersalty'))
        self.session.add(Domain(name='facebook.com', salt='notsomuch'))
        self.session.commit()
        self.pwm = PWM()
        self.pwm.bootstrap(self.tmp_db.name)


    def tearDown(self):
        os.remove(self.tmp_db.name)


    def test_get_salt(self):
        # sha1 hexdigest of secret:example.com:NaCl
        expected = 'e7b5038ba1a704e19b8326bc9592329d73ed7351'
        salt = self.pwm.get_domain('example.com').salt
        self.assertEqual(salt, 'NaCl')


    def test_add_domain(self):
        new_domain = self.pwm.create_domain('othersite.com')
        key = new_domain.derive_key('secret')

        # should now get the same key on second attempt
        fetched_domain = self.pwm.get_domain('othersite.com')
        self.assertEqual(fetched_domain.derive_key('secret'), key)


    def test_domain_search(self):
        results = self.pwm.search('example')
        self.assertEqual(len(results), 2)
        results = self.pwm.search('bank')
        self.assertEqual(len(results), 0)


    def test_no_duplicates(self):
        # PY26: If we drop support for python 2.6, this can be rewritten to use assertRaises as a
        # context manager, which is better for readability
        self.assertRaises(DuplicateDomainException, self.pwm.create_domain, 'example.com')


class PWMNotReadyTest(unittest.TestCase):

    def test_not_ready(self):
        pwm = PWM()
        self.assertRaises(NotReadyException, pwm.get_domain, 'example.com')
