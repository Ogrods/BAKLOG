import sys

import pytest

if sys.platform != "win32":
    pytest.skip("amazon_client requires Windows (DPAPI)", allow_module_level=True)
import clients.amazon_client as amazon_client


def _fuel_ent(sku="the_secret_of_monkey_island_special_edition_game"):
    return {
        "ProductTitle": "The Secret of Monkey Island: Special Edition",
        "ProductLine": "Twitch:FuelGame",
        "ProductSku": sku,
        "ProductIdStr": "6ea8a67f-b21c-425b-9d1b-ce207e30ae2f",
        "ProductId": {"Id": "6ea8a67f-b21c-425b-9d1b-ce207e30ae2f"},
    }


def _native_ent():
    return {
        "ProductTitle": "The Curse of Monkey Island",
        "ProductLine": "Sonic:Game",
        "ProductSku": "amzn1.resource.acbf3c47-c3aa-9d99-2819-9e641a1a92bc",
        "ProductIdStr": "amzn1.adg.product.fe83dbda-6966-4ba6-b252-33faa24034e4",
        "ProductId": {"Id": "amzn1.adg.product.fe83dbda-6966-4ba6-b252-33faa24034e4"},
    }


class TestIsExternalPrimeClaim:
    def test_fuel_promo_is_external(self):
        assert amazon_client._is_external_prime_claim(_fuel_ent()) is True

    def test_native_adg_title_is_kept(self):
        assert amazon_client._is_external_prime_claim(_native_ent()) is False

    def test_non_twitch_line_is_kept(self):
        ent = _fuel_ent()
        ent["ProductLine"] = "Sonic:Game"
        assert amazon_client._is_external_prime_claim(ent) is False

    def test_twitch_line_with_adg_id_is_kept(self):
        ent = _fuel_ent()
        ent["ProductIdStr"] = "amzn1.adg.product.abc"
        ent["ProductId"] = {"Id": "amzn1.adg.product.abc"}
        assert amazon_client._is_external_prime_claim(ent) is False

    def test_missing_product_line_is_kept(self):
        assert amazon_client._is_external_prime_claim({"ProductTitle": "X"}) is False
