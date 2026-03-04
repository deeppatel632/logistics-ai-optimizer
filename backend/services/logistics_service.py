from services.optimization.route_optimizer import optimize_routes


def optimize_shipments(shipments, warehouse):

    locations = []

    locations.append((warehouse.latitude, warehouse.longitude))

    for shipment in shipments:
        locations.append(
            (shipment.destination_lat, shipment.destination_lon)
        )

    routes = optimize_routes(locations)

    return routes