# -*- coding: utf-8 -*-
"""Pruebas unitarias de la comprobación de sesión del endpoint POS."""
from unittest.mock import Mock

from odoo.addons.lba_print_connector.controllers.main import _authorized_pos_config
from odoo.tests.common import TransactionCase


class _Empty:
    def __bool__(self):
        return False


class _Model:
    def __init__(self, result=None):
        self.result = result
        self.search_calls = []

    def search(self, domain, limit=None):
        self.search_calls.append((domain, limit))
        return self.result or _Empty()

    def browse(self, *args, **kwargs):
        return _Empty()


class _Env:
    uid = 41

    def __init__(self, is_pos_user=True, config=None, session=None):
        self.user = Mock()
        self.user.has_group.return_value = is_pos_user
        self.models = {
            "pos.config": _Model(config),
            "pos.session": _Model(session),
        }

    def __getitem__(self, name):
        return self.models[name]


class TestLbaControllerAuthorization(TransactionCase):
    def test_non_pos_user_is_rejected_before_orm_lookup(self):
        env = _Env(is_pos_user=False)
        config, error = _authorized_pos_config(env, 3, 5)
        self.assertFalse(config)
        self.assertEqual(error, "pos_user_required")
        self.assertEqual(env.models["pos.config"].search_calls, [])
        env.user.has_group.assert_called_once_with("point_of_sale.group_pos_user")


    def test_missing_config_or_session_is_rejected(self):
        env = _Env()
        config, error = _authorized_pos_config(env, 3, None)
        self.assertFalse(config)
        self.assertEqual(error, "pos_session_required")
        self.assertEqual(env.models["pos.config"].search_calls, [])


    def test_authorization_search_binds_open_session_to_user_and_config(self):
        authorized_config = object()
        opened_session = object()
        env = _Env(config=authorized_config, session=opened_session)

        config, error = _authorized_pos_config(env, "3", "5")

        self.assertIs(config, authorized_config)
        self.assertFalse(error)
        self.assertEqual(env.models["pos.config"].search_calls, [(
            [("id", "=", 3), ("lba_active", "=", True)], 1)])
        self.assertEqual(env.models["pos.session"].search_calls, [(
            [("id", "=", 5), ("config_id", "=", 3),
             ("user_id", "=", 41), ("state", "=", "opened")], 1)])


    def test_session_not_found_for_current_user_is_rejected(self):
        env = _Env(config=object(), session=None)
        config, error = _authorized_pos_config(env, 3, 5)
        self.assertFalse(config)
        self.assertEqual(error, "pos_session_required")
