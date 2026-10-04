"""How a gRPC operation and a stub name the same service.

protoc puts only the service name in a generated class, so a server
implementation or client stub says `OrdersService` while the proto declares
`petclinic.orders.OrdersService/GetOrder`. Binding the two (R5) and
reconciling them (drift) are one decision, so it lives here once.
"""


def operation_service_names(op_key: str) -> tuple[str, str]:
    """`pkg.OrdersService/GetOrder` -> `("pkg.ordersservice", "ordersservice")`."""
    service_full = op_key.rpartition("/")[0].lower()
    return service_full, service_full.rpartition(".")[2]


def stub_service_name(claim) -> str:
    """The service a server implementation or client stub names."""
    return str(claim.attrs.get("service") or claim.key).lower()
