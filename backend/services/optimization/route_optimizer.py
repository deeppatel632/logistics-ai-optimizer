from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import math


def calculate_distance(coord1, coord2):
    """
    Calculate distance between two coordinates using Haversine formula.
    """
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    R = 6371  # Earth radius km

    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def create_distance_matrix(locations):

    matrix = []

    for from_node in locations:
        row = []

        for to_node in locations:
            distance = calculate_distance(from_node, to_node)
            row.append(int(distance * 1000))

        matrix.append(row)

    return matrix


def optimize_routes(locations, vehicle_count=1):

    distance_matrix = create_distance_matrix(locations)

    manager = pywrapcp.RoutingIndexManager(
        len(distance_matrix),
        vehicle_count,
        0
    )

    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):

        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)

        return distance_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)

    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()

    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        return None

    routes = []

    for vehicle_id in range(vehicle_count):

        index = routing.Start(vehicle_id)
        route = []

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route.append(node)

            index = solution.Value(routing.NextVar(index))

        routes.append(route)

    return routes
