from fraud_detection.data.adapters import (
    adapt_banksim,
    adapt_elliptic_transaction,
    adapt_ibm_aml,
    adapt_ieee_cis,
    adapt_paysim,
    adapt_ulb_creditcard,
    stack_datasets,
    training_pairs,
)
from fraud_detection.schema import LabelType


def test_sources_keep_their_own_label_types():
    paysim = adapt_paysim(
        {
            "step": 1,
            "type": "TRANSFER",
            "amount": 100,
            "nameOrig": "C1",
            "nameDest": "C2",
            "oldbalanceOrg": 100,
            "newbalanceOrig": 0,
            "isFraud": 1,
        }
    )
    aml = adapt_ibm_aml(
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
    stacked = stack_datasets([[paysim], [aml]])
    assert [item.dataset for item in stacked] == ["paysim", "ibm_aml"]
    assert [item.label_type for item in stacked] == [LabelType.ACCOUNT_TAKEOVER, LabelType.AML_LAUNDERING]


def test_ulb_pca_columns_stay_out_of_the_canonical_amount():
    row = {"Time": 10, "Amount": 25.5, "Class": 1, "V1": 0.2, "V2": -0.4}
    adapted = adapt_ulb_creditcard(row, index=3)
    assert adapted.label_type == LabelType.CARD_FRAUD
    assert adapted.metadata["pca"] == {"V1": 0.2, "V2": -0.4}
    assert adapted.sender_id == "ulb-row-3"


def test_unknown_elliptic_rows_are_not_legitimate_negatives():
    unknown = adapt_elliptic_transaction({"txId": "t1", "class": "unknown", "time step": 2})
    licit = adapt_elliptic_transaction({"txId": "t2", "class": "2", "time step": 2})
    pairs = training_pairs([unknown, licit])
    assert [item.transaction_id for item, _ in pairs] == ["elliptic-t2"]
    assert pairs[0][1] is None


def test_banksim_strips_quotes_and_uses_midday():
    adapted = adapt_banksim(
        {
            "step": "0",
            "customer": "'C1'",
            "merchant": "'M1'",
            "amount": "10.5",
            "category": "'es_transportation'",
            "fraud": "1",
        }
    )
    assert adapted.sender_id == "C1"
    assert adapted.receiver_id == "M1"
    assert adapted.channel == "card"
    assert adapted.timestamp.hour == 12
    assert adapted.label_type.value == "CARD_FRAUD"
    assert adapted.metadata["data_origin"] == "REAL_PUBLIC_DATA"
    assert adapted.metadata["source_kind"] == "synthetic_simulated"


def test_ieee_adapter_marks_the_non_commercial_limit():
    adapted = adapt_ieee_cis({"TransactionID": "9", "TransactionDT": 15, "TransactionAmt": 40, "isFraud": 0})
    assert adapted.metadata["non_commercial_only"] is True
    assert adapted.label_type is None
