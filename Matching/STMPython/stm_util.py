"""

- 2017-04-12 included [0,0,0] in the default neighbours should not be too
  critical, just a backup measure.

"""

import math
from collections import Counter
import itertools
import datetime
import sys
from time import perf_counter

import numpy as np

from transonic import boost, Tuple, List, Array

from util_groupby import make_groups_by_cell_cam


@boost
def expand_all_neighbours_uniq(
    points: Array[np.int32, "2d"], neighbours: Array[np.int32, "2d"]
):
    """Take positions and neighbours and create p+n for each n in neighbours
    and for each p
    """

    nb_points = points.shape[0]
    nb_neighbours = neighbours.shape[0]
    big = np.empty((nb_points * nb_neighbours, 3), dtype=np.int32)

    for index_point in range(points.shape[0]):
        point = points[index_point]
        for index_delta in range(neighbours.shape[0]):
            delta = neighbours[index_delta]
            big[index_point * nb_neighbours + index_delta, :] = point + delta

    multiplicator = 2 ** 10
    assert big.max() < multiplicator
    as_ints = (
        multiplicator ** 2 * big[:, 0] + multiplicator * big[:, 1] + big[:, 2]
    )

    indices = as_ints.argsort()
    as_ints_sorted = as_ints[indices]
    big = big[indices, :]

    diffs = np.array(np.diff(as_ints_sorted), bool)

    result = np.empty((diffs.sum() + 1, 3), dtype=np.int32)

    index_result = 0
    result[index_result] = big[0, :]
    index_result = 1

    for index, diff in enumerate(diffs):
        if not diff:
            continue
        result[index_result] = big[index + 1, :]
        index_result += 1

    return result


def joinlists(boundaries):
    "'Flatten' a list of lists to a single list"
    # return list(itertools.chain.from_iterable(boundaries))
    return [value for sub_list in boundaries for value in sub_list]


def sign(x):
    "Custom sign function that gives either -1 or 1, also for input value 0"
    if x < 0:
        return -1
    else:
        return 1


def special_division(a, b):
    "Division that spawns -infinity in case the denominator is 0"
    if b == 0:
        return -math.inf
    else:
        return a / b


def find_index_bin(boundaries, value):
    """
    Gives index in which 'bin' the value value will fall with boundaries 'boundaries', -1
    = outside

    `boundaries` has to be sorted to make this work properly

    Implemented with O(Log(N)) scaling, basic idea is to reduce by factors of 2
    every time until 1 bin is left

    Greedy: it will take the first bin if the right boundary exactly matches value
    """
    mn = 0
    mx = len(boundaries) - 1
    if abs(boundaries[0] - value) < 10 ** -8:
        return 0

    if abs(boundaries[mn] - value) < 10 ** -8:
        return mn - 1

    if boundaries[mn] <= value <= boundaries[mx]:
        while mx - mn > 1:
            # print('min',mn,'max',mx)
            # Banker's rounding but does not matter, still O(Log(N)) scaling
            trial = round((mn + mx) / 2)
            if value > boundaries[trial]:
                mn = trial
            else:
                mx = trial
        # print('Final: min',mn,'max',mx)
        return mn
    else:
        return -1


def vector_norm(y):
    "Euclidean distance of a list (faster than np.linalg.norm(y)!)"
    x = np.array(y)
    return np.sqrt(x.dot(x))


def square_vector_norm(y):
    x = np.array(y)
    return x.dot(x)


def normalize(v):
    norm = vector_norm(v)
    if norm == 0:
        return v
    return v / norm


@boost
def closest_point_to_lines2(
    points: List[Tuple[float, float, float]],
    vectors: List[Tuple[float, float, float]],
):
    p1 = np.array(points[0])
    p2 = np.array(points[1])
    v1 = np.array(vectors[0])
    v2 = np.array(vectors[1])
    # a = np.dot(v1,v1)          # Assuming v is normalized => length 1
    b = 2 * np.dot(p1 - p2, v1)
    c = 2 * np.dot(v1, v2)
    d = 2 * np.dot(p2 - p1, v2)
    # e = np.dot(v2,v2)          # Assuming v is normalized => length 1
    # f = np.dot(p1, p1) + np.dot(p2, p2)
    # s = (2*a*d + b*c)/(c**2-4*a*e)
    s = (2 * d + b * c) / (c ** 2 - 4)  # Assuming v is normalized => a=e=1
    # t = (c*s - b)/(2*a)
    t = (c * s - b) / 2  # Assuming v is normalized => a=e=1
    sol = (p1 + t * v1 + p2 + s * v2) / 2
    # # Assuming v is normalized => a=1
    # d1 = vector_norm(np.cross(v1,p1-sol))/np.sqrt(a)
    d1 = vector_norm(np.cross(v1, p1 - sol))
    # # Must be the same as d1 for two lines!
    # d2 = np.linalg.norm(np.cross(sol-p1,sol-p1+v1))/np.linalg.norm(v1)
    return sol.tolist(), float(d1)


A2 = "float64[:, :]"


@boost
def prepare_linalg_solve(a: A2, d: A2):
    length = len(a)
    rhs = np.zeros(3, dtype=np.float64)
    lhs = length * np.identity(3)
    for i in range(length):
        rhs += a[i] - d[i] * np.dot(a[i], d[i])
        lhs -= np.outer(d[i], d[i])
    return lhs, rhs


@boost
def compute_distance(a: A2, d: A2, sol: "float64[:]"):
    dists = list(map(lambda a, d: square_vector_norm(np.cross(sol - a, d)), a, d))
    distance = vector_norm(dists) * np.sqrt(1 / len(a))
    return float(distance)


def closest_point_to_lines(points, vectors):
    """...

    Note: 9% of the time spent here (CProfile)
    """
    assert len(points) > 2
    a = np.array(points)
    # Assuming v is normalized already
    d = np.array(vectors)
    lhs, rhs = prepare_linalg_solve(a, d)
    sol = np.linalg.solve(lhs, rhs)
    return sol.tolist(), compute_distance(a, d, sol)


def directional_voxel_traversal(point, vector_ray, cell_bounds):
    """3D dimensional voxel traversal

    Gives cell-indices back starting from `point` and moving in the direction
    given by `vector_ray`, subject two cell_bounds.
    """
    # point, vector_ray, and cell_bounds should be 3 dimensional
    if not len(point) == len(vector_ray) == len(cell_bounds) == 3:
        raise ValueError("dimension mismatch!")

    # cell_index_point: Tuple[int, int, int]
    cell_index_point = tuple(map(find_index_bin, cell_bounds, point))

    if -1 in cell_index_point or vector_norm(vector_ray) == 0:
        raise ValueError(
            f"ray starts outside cell_bounds!\np: {point}\n"
            f"v: {vector_ray}\ncell index: {cell_index_point}\n"
        )

    return kernel_directional_voxel_traversal(
        point, vector_ray, cell_bounds, cell_index_point
    )


@boost
def kernel_directional_voxel_traversal(
    point: Tuple[float, float, float],
    vector_ray: Tuple[float, float, float],
    cell_bounds: List[Array[float, "1d"]],
    cell_index_point: Tuple[int, int, int],
):

    times_axes = {}
    for index_axe, bounds_axe in enumerate(cell_bounds):
        relative_bounds = bounds_axe - point[index_axe]
        vector_ray_component = vector_ray[index_axe]
        if vector_ray_component == 0:
            continue
        else:
            times_axe = relative_bounds / vector_ray_component

        times_axe = times_axe[times_axe > 0]
        times_axes[index_axe] = times_axe

    exit_times = [times.max() for times in times_axes.values()]
    exit_time = min(exit_times)

    for index_axe, times_axe in times_axes.items():
        times_axes[index_axe] = times_axe[times_axe < exit_time]

    times_concat = np.concatenate(list(times_axes.values()))

    axes = []
    for index_axe, times_axe in times_axes.items():
        tmp_axe = np.empty(len(times_axe), dtype=np.int8)
        tmp_axe.fill(index_axe)
        axes.append(tmp_axe)

    axes_concat = np.concatenate(axes)
    axes_sorted = axes_concat[times_concat.argsort()]

    directions = [sign(component) for component in vector_ray]

    cell = np.array(cell_index_point)

    out = np.empty((len(axes_sorted) + 1, 3), np.int32)
    out[0, :] = cell
    for index, index_axe in enumerate(axes_sorted):
        cell[index_axe] += directions[index_axe]
        out[index + 1, :] = cell

    # all cells traversed by the ray (sorted by "time")
    return out


def at_face(bmin, bmax, hitb):
    return bmin <= hitb <= bmax


def prepare_ray(point, v, bounds):
    """
    Projects ray (defined by point, v) onto an AABB (axis aligned bounding box).

    Returns (bool_hit, bool_inside, position, vector_ray)

    - bool_hit tells if it hits AABB,
    - bool_inside tells if it is projected
    - position: the new position or [] in case it misses.
    - vector_ray: the normalized vector

    Note that ray can be projected onto an AABB with negative 'time'...

    Note: very quick so no need to optimize.
    """

    xmin = bounds[0][0]
    xmax = bounds[0][1]
    ymin = bounds[1][0]
    ymax = bounds[1][1]
    zmin = bounds[2][0]
    zmax = bounds[2][1]
    x = point[0]
    y = point[1]
    z = point[2]
    vector_ray = tuple(normalize(v))  # v is normalized
    vx, vy, vz = vector_ray
    if xmin < x < xmax and ymin < y < ymax and zmin < z < zmax:
        return [
            True,
            True,
            tuple(point),
            vector_ray,
        ]  # Return False and original point
    else:
        t = list(
            map(
                special_division,
                [xmin - x, xmax - x, ymin - y, ymax - y, zmin - z, zmax - z],
                [vx, vx, vy, vy, vz, vz],
            )
        )
        ip = [0 for tmp in range(6)]
        for i in range(6):
            ti = t[i]
            if abs(ti) == math.inf:
                ip[i] = [math.inf, math.inf, math.inf]
            else:
                ip[i] = [x + vx * ti, y + vy * ti, z + vz * ti]

    atfacex1 = at_face(ymin, ymax, ip[0][1]) and at_face(zmin, zmax, ip[0][2])
    atfacex2 = at_face(ymin, ymax, ip[1][1]) and at_face(zmin, zmax, ip[1][2])
    atfacey1 = at_face(xmin, xmax, ip[2][0]) and at_face(zmin, zmax, ip[2][2])
    atfacey2 = at_face(xmin, xmax, ip[3][0]) and at_face(zmin, zmax, ip[3][2])
    atfacez1 = at_face(xmin, xmax, ip[4][0]) and at_face(ymin, ymax, ip[4][1])
    atfacez2 = at_face(xmin, xmax, ip[5][0]) and at_face(ymin, ymax, ip[5][1])
    data = [t, [atfacex1, atfacex2, atfacey1, atfacey2, atfacez1, atfacez2], ip]
    # Data will be a list of lists, each having the form: time-till-hit, hits
    # face (boolean), position it hits a plane
    data = list(zip(*data))
    # Select only those that hit a face #don't change to 'is True' numpy bool
    # possibility
    data = list(filter(lambda xx: xx[1], data))
    if len(data) > 0:
        # Sort by arrival time (time till hit)
        data = sorted(data, key=lambda x: x[0])
        # Position it hits the plane of first-hit
        return [True, False, tuple(data[0][2]), vector_ray]
    else:
        return [False, False, tuple(), vector_ray]


def make_ray_database(rays, boundingbox, log_print):

    # Store a dictionary of (cameraid, ray_id): [pos, direction]
    raydb = {}
    valid_rays = []  # Store the transformed rays
    num_rays_per_camera = Counter()  # Store the number of rays per camera
    invalidcounter = Counter()  # Store the number that are invalid

    # First element is camera ID
    INDEX_CAM = 0
    # Second element is the ray ID
    INDEX_RAY = 1

    for ray in rays:
        cam_id = ray[INDEX_CAM]
        ray_id = ray[INDEX_RAY]
        num_rays_per_camera[cam_id] += 1

        pp = list(ray[2:5])
        vv = list(ray[5:8])
        bool_hit, bool_inside, position, vector_ray = prepare_ray(
            pp, vv, boundingbox
        )

        if bool_hit:  # If it does not miss (hit or inside)
            raydb[(cam_id, ray_id)] = [position, vector_ray]
            valid_rays.append([cam_id, ray_id, bool_inside, position, vector_ray])
        else:
            invalidcounter[cam_id] += 1

    log_print(
        "# of rays for each camera:",
        dict(num_rays_per_camera),
        "\n# of rays that miss the bounding box:",
        dict(invalidcounter),
    )

    return raydb, valid_rays, num_rays_per_camera


def compute_cells_traversed_by_rays(valid_rays, bounds, neighbours):

    t_start = perf_counter()

    cells_all = []
    cam_ray_ids_all = []
    for ray in valid_rays:
        cam_id, ray_id, bool_inside, position, vector_ray = ray
        if bool_inside:  # Ray is inside, traverse both forward and backward
            cells_1ray = np.vstack(
                (
                    directional_voxel_traversal(position, vector_ray, bounds),
                    directional_voxel_traversal(
                        position,
                        tuple(map(lambda x: -x, vector_ray)),
                        bounds,
                    ),
                )
            )
        else:  # Ray is at edge, traverse in forward direction only
            cells_1ray = directional_voxel_traversal(position, vector_ray, bounds)

        # Expand in neighbourhood and remove duplicates
        cells = expand_all_neighbours_uniq(cells_1ray, neighbours)

        nb_cells = cells.shape[0]

        cells_all.append(cells)

        cam_id_arr = np.empty((nb_cells, 1), dtype=np.int32)
        cam_id_arr.fill(cam_id)
        ray_id_arr = np.empty((nb_cells, 1), dtype=np.int32)
        ray_id_arr.fill(ray_id)
        cam_ray_ids = np.hstack((cam_id_arr, ray_id_arr))

        cam_ray_ids_all.append(cam_ray_ids)

    print(
        "compute_cells_traversed_by_rays done in "
        f"{perf_counter() - t_start:.2f} s"
    )

    return np.vstack(cells_all), np.vstack(cam_ray_ids_all)


def uniquify_candidates(candidates):
    return list(set(candidates))


def make_candidates(traversed, candidates0, raydb, log_print):

    t_start = perf_counter()

    # All combinations between all cameras
    candidates = list(
        map(
            lambda x: [tuple(sorted(tup)) for tup in itertools.product(*x)],
            traversed,
        )
    )
    # Flatten a list of lists to a single list
    candidates = joinlists(candidates)

    candidates.extend(candidates0)

    log_print("Flattened list of candidates:", len(candidates))
    # Delete duplicates, flattened list as tag
    candidates = uniquify_candidates(candidates)

    log_print("Duplicate candidates removed:", len(candidates))
    candidates = sorted(candidates)

    # log_print("Computing match position and quality of candidates...")
    newcandidates = []
    for candidate in candidates:
        try:
            candidate[2]
        except IndexError:
            # then we know that len(candidate) == 2:
            p0, v0 = raydb[candidate[0]]
            p1, v1 = raydb[candidate[1]]
            points = [p0, p1]
            vectors = [v0, v1]
            closest_point, distance = closest_point_to_lines2(points, vectors)
        else:
            rays_data = [raydb[cam_ray_id] for cam_ray_id in candidate]
            points = [ray_data[0] for ray_data in rays_data]
            vectors = [ray_data[1] for ray_data in rays_data]
            closest_point, distance = closest_point_to_lines(points, vectors)

        newcandidates.append([candidate, closest_point, distance])

    # hullpts = [[20.0,5.0,165.0],[20.0,10.0,160.0],[20.0,10.0,165.0],[20.0,15.0,160.0],[20.0,15.0,165.0],[20.0,20.0,160.0],[20.0,20.0,165.0],[20.0,25.0,160.0],[20.0,25.0,165.0],[25.0,0.0,165.0],[25.0,0.0,170.0],[25.0,5.0,155.0],[25.0,10.0,155.0],[25.0,15.0,155.0],[25.0,20.0,155.0],[25.0,25.0,155.0],[25.0,25.0,175.0],[25.0,30.0,170.0],[25.0,35.0,155.0],[25.0,35.0,160.0],[30.0,-5.0,170.0],[30.0,0.0,160.0],[30.0,5.0,150.0],[30.0,10.0,150.0],[30.0,15.0,150.0],[30.0,20.0,150.0],[30.0,25.0,150.0],[30.0,25.0,180.0],[30.0,30.0,150.0],[30.0,30.0,180.0],[30.0,35.0,175.0],[30.0,40.0,165.0],[30.0,45.0,155.0],[35.0,-10.0,175.0],[35.0,-5.0,165.0],[35.0,-5.0,180.0],[35.0,0.0,155.0],[35.0,10.0,145.0],[35.0,15.0,145.0],[35.0,20.0,145.0],[35.0,25.0,185.0],[35.0,30.0,185.0],[35.0,35.0,150.0],[35.0,35.0,185.0],[35.0,40.0,180.0],[35.0,45.0,155.0],[35.0,45.0,170.0],[35.0,50.0,160.0],[40.0,-10.0,175.0],[40.0,-10.0,180.0],[40.0,-5.0,165.0],[40.0,0.0,155.0],[40.0,5.0,145.0],[40.0,10.0,145.0],[40.0,15.0,145.0],[40.0,30.0,150.0],[40.0,40.0,180.0],[40.0,45.0,155.0],[40.0,45.0,175.0],[40.0,50.0,160.0],[40.0,50.0,165.0],[45.0,-5.0,175.0],[45.0,0.0,165.0],[45.0,5.0,155.0],[45.0,10.0,150.0],[45.0,15.0,150.0],[45.0,40.0,180.0],[45.0,50.0,160.0],[45.0,50.0,165.0],[50.0,15.0,160.0],[50.0,20.0,160.0],[50.0,25.0,175.0],[50.0,30.0,175.0],[50.0,35.0,175.0],[50.0,45.0,165.0],[55.0,15.0,170.0],[55.0,20.0,170.0],[55.0,25.0,170.0],[55.0,30.0,170.0],[55.0,35.0,170.0],[55.0,40.0,170.0]];
    # delaun = sps.Delaunay(hullpts)  # Define the Delaunay triangulation
    # inq = delaun.find_simplex([x[1] for x in newcandidates])>0
    # inq = inq.tolist();
    # print(inq)
    # print(type(inq))
    # newcandidates = list(map(lambda x,y: x + [y],newcandidates,inq))

    candidates = newcandidates
    # log_print("Sorting candidate matches by quality of match...")
    # sort by number of cameras then by error
    candidates = sorted(candidates, key=lambda x: (-len(x[0]), x[2]))
    # log_print("Here are upto 9999 of the best matches:")
    # log_print("Index, [cam_id ray_id ....] Position, Mean square distance")
    # print("num candidates:",len(candidates))
    # for i in range(1,len(candidates),100):
    #    print(i,candidates[i])

    print(f"make_candidates done in {perf_counter() - t_start:.2f} s")

    return candidates


def make_approved_matches(candidates, maxdistance, max_matches_per_ray):
    t_start = perf_counter()
    print(f"make_approved_matches", end="")
    approved_matches = []  # Store approved candidates
    matchcounter = Counter()  # Keep track of how many they are matched
    for cand in candidates:
        if cand[2] < maxdistance:
            valid = True
            for idpair in cand[0]:
                if matchcounter[tuple(idpair)] >= max_matches_per_ray:
                    valid = False
                    break
            if valid:
                for idpair in cand[0]:
                    matchcounter[tuple(idpair)] += 1

                approved_matches.append(list(cand))

    print(f" (done in {perf_counter() - t_start:.2f} s)")

    return approved_matches


def space_traversal_matching(
    raydata,
    boundingbox,
    nx=75,
    ny=75,
    nz=75,
    cam_match=2,
    max_matches_per_ray=2,
    maxdistance=999.9,
    neighbours=6,
    logfile="",
):

    if not (
        len(boundingbox) == 3
        and len(boundingbox[0]) == 2
        and len(boundingbox[1]) == 2
        and len(boundingbox[2]) == 2
        and nx >= 5
        and ny >= 5
        and nz >= 5
    ):
        print(
            "Something went wrong:\n"
            "Bounding box should be of the form "
            "[[xmin,xmax],[ymin,ymax],[zmin,zmax]] {boundingbox}\n",
            "nx,ny,nz should be >=5 otherwise you will do a lot of comparisons!",
            [nx, ny, nz],
        )
        return []

    if neighbours == 0:
        neighbours = [[0, 0, 0]]
    elif neighbours == 6:
        # fmt: off
        neighbours = [
            [-1, 0, 0], [0, -1, 0], [0, 0, -1], [0, 0, 1], [0, 1, 0],
            [1, 0, 0], [0, 0, 0]
        ]
        # fmt: on
    elif neighbours == 18:
        # fmt: off
        neighbours = [
            [-1, -1, 0], [-1, 0, -1], [-1, 0, 0], [-1, 0, 1], [-1, 1, 0],
            [0, -1, -1], [0, -1, 0], [0, -1, 1], [0, 0, -1], [0, 0, 1],
            [0, 1, -1], [0, 1, 0], [0, 1, 1], [1, -1, 0], [1, 0, -1],
            [1, 0, 0], [1, 0, 1], [1, 1, 0], [0, 0, 0]
        ]
        # fmt: on
    elif neighbours == 26:
        # fmt: off
        neighbours = [
            [-1, -1, -1], [-1, -1, 0], [-1, -1, 1], [-1, 0, -1], [-1, 0, 0],
            [-1, 0, 1], [-1, 1, -1], [-1, 1, 0], [-1, 1, 1], [0, -1, -1],
            [0, -1, 0], [0, -1, 1], [0, 0, -1], [0, 0, 1], [0, 1, -1],
            [0, 1, 0], [0, 1, 1], [1, -1, -1], [1, -1, 0], [1, -1, 1],
            [1, 0, -1], [1, 0, 0], [1, 0, 1], [1, 1, -1], [1, 1, 0],
            [1, 1, 1], [0, 0, 0]
        ]
        # fmt: on
    if not isinstance(neighbours, list):
        raise TypeError(
            "Neighbours should be a 0, 6, 18, or 26 or "
            f"a list of triplets: {neighbours}"
        )

    neighbours = np.array(neighbours, dtype=np.int32)

    if logfile:

        def log_print(*args):
            with open(logfile, "a") as flog:
                flog.write(" ".join(map(str, list(args))) + "\n")
            print(*args)

    else:

        def log_print(*args):
            print(*args)

    log_print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    bounds = [
        np.linspace(limits[0], limits[1], n + 1)
        for limits, n in zip(boundingbox, (nx, ny, nz))
    ]

    log_print("# of cells:", nx * ny * nz)
    rays = list(raydata)

    # Prepare the rays so that they are inside the box or on the side.
    raydb, valid_rays, num_rays_per_camera = make_ray_database(
        rays, boundingbox, log_print
    )

    if len(dict(num_rays_per_camera)) > 10:
        log_print(
            "# of cameras is large:",
            len(dict(num_rays_per_camera)),
            " Double check the input!",
        )
        sys.exit(1)

    cells_all, cam_ray_ids = compute_cells_traversed_by_rays(
        valid_rays, bounds, neighbours
    )

    del bounds, neighbours

    log_print("# of voxels traversed after expansion:", len(cells_all))

    traversed, candidates0 = make_groups_by_cell_cam(
        cells_all, cam_ray_ids, cam_match
    )

    log_print("Sorted and grouped by cell index. # of groups:", len(traversed))

    candidates = make_candidates(traversed, candidates0, raydb, log_print)

    log_print(
        f"Selecting the best matches with up to {max_matches_per_ray}",
        f"match(es)/ray out of {len(candidates)} candidates",
    )

    # now we want to pick the best matches first and match each ray at most
    # max_matches_per_ray

    approved_matches = make_approved_matches(
        candidates, maxdistance, max_matches_per_ray
    )

    log_print(
        "Selecting done.",
        len(approved_matches),
        "matched found (out of",
        len(candidates),
        "candidates)",
    )
    # print("Here are the approved matches:")
    # print("Index, [cam_id ray_id ....] Position, Mean square distance")

    return approved_matches
