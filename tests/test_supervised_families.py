from fraud_detection.data.adapters import adapt_banksim, adapt_ibm_aml, adapt_paysim
from fraud_detection.models.supervised import eligible_supervised_types
from fraud_detection.schema import Transaction


def test_paysim_mobile_money_is_takeover_only():
    adapted = adapt_paysim(
        {
            "step": 1,
            "type": "CASH_OUT",
            "amount": 100,
            "nameOrig": "C1",
            "nameDest": "C2",
            "oldbalanceOrg": 100,
            "newbalanceOrig": 0,
            "isFraud": 1,
        }
    )
    assert eligible_supervised_types(adapted) == frozenset({"ACCOUNT_TAKEOVER"})


def test_paysim_transfer_is_not_card_or_laundering():
    adapted = adapt_paysim(
        {
            "step": 4,
            "type": "TRANSFER",
            "amount": 50,
            "nameOrig": "C1",
            "nameDest": "C2",
            "oldbalanceOrg": 50,
            "newbalanceOrig": 0,
            "isFraud": 1,
        }
    )
    allowed = eligible_supervised_types(adapted)
    assert "CARD_FRAUD" not in allowed
    assert "AML_LAUNDERING" not in allowed
    assert allowed == frozenset({"ACCOUNT_TAKEOVER"})


def test_banksim_payment_is_card_only():
    adapted = adapt_banksim(
        {
            "step": "0",
            "customer": "C1",
            "merchant": "M1",
            "amount": "10.5",
            "category": "es_transportation",
            "fraud": "1",
        }
    )
    assert eligible_supervised_types(adapted) == frozenset({"CARD_FRAUD"})


def test_ibm_wire_is_laundering_and_credit_card_format_is_card():
    wire = adapt_ibm_aml(
        {
            "Timestamp": "2022/09/01 00:20",
            "From Bank": "10",
            "Account": "100",
            "To Bank": "11",
            "Account.1": "200",
            "Amount Paid": 500,
            "Payment Currency": "USD",
            "Payment Format": "Wire",
            "Is Laundering": 1,
        }
    )
    card_format = adapt_ibm_aml(
        {
            "Timestamp": "2022/09/01 00:21",
            "From Bank": "10",
            "Account": "100",
            "To Bank": "11",
            "Account.1": "200",
            "Amount Paid": 500,
            "Payment Currency": "USD",
            "Payment Format": "Credit Card",
            "Is Laundering": 1,
        }
    )
    assert eligible_supervised_types(wire) == frozenset({"AML_LAUNDERING"})
    assert eligible_supervised_types(card_format) == frozenset({"CARD_FRAUD"})


def test_dataset_name_does_not_select_the_card_head():
    transfer = Transaction(
        transaction_id="plain-1",
        timestamp="2024-06-01T12:00:00",
        amount=2500,
        currency="USD",
        transaction_type="transfer",
        sender_id="demo-sender",
        receiver_id="demo-receiver",
        dataset="banksim",
    )
    assert eligible_supervised_types(transfer) == frozenset({"AML_LAUNDERING"})
    assert "CARD_FRAUD" not in eligible_supervised_types(transfer)


def test_unknown_type_has_no_specialist():
    pix = Transaction(
        transaction_id="pix-1",
        timestamp="2024-06-01T12:00:00",
        amount=40,
        currency="BRL",
        transaction_type="pix",
        sender_id="s",
        receiver_id="r",
    )
    assert eligible_supervised_types(pix) == frozenset()


def test_account_channel_is_takeover_not_card():
    takeover = Transaction(
        transaction_id="ato-1",
        timestamp="2024-04-16T03:15:00",
        amount=28000,
        sender_id="AT00",
        receiver_id="ATF00",
        channel="mobile",
        device_id="new-device",
        dataset="tunisia_synth",
    )
    assert eligible_supervised_types(takeover) == frozenset({"ACCOUNT_TAKEOVER"})
