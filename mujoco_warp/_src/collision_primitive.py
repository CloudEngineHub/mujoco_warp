# Copyright 2025 The Newton Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import warp as wp

from .math import closest_segment_point
from .math import closest_segment_to_segment_points
from .math import make_frame
from .math import normalize_with_norm
from .types import MJ_MINVAL
from .types import Data
from .types import GeomType
from .types import Model
from .types import vec5

wp.set_module_options({"enable_backward": False})


class vec8f(wp.types.vector(length=8, dtype=wp.float32)):
  pass


class mat43f(wp.types.matrix(shape=(4, 3), dtype=wp.float32)):
  pass


class mat83f(wp.types.matrix(shape=(8, 3), dtype=wp.float32)):
  pass


@wp.struct
class Geom:
  pos: wp.vec3
  rot: wp.mat33
  normal: wp.vec3
  size: wp.vec3
  vertadr: int
  vertnum: int


@wp.func
def _geom(
  gid: int,
  m: Model,
  geom_xpos: wp.array(dtype=wp.vec3),
  geom_xmat: wp.array(dtype=wp.mat33),
) -> Geom:
  geom = Geom()
  geom.pos = geom_xpos[gid]
  rot = geom_xmat[gid]
  geom.rot = rot
  geom.size = m.geom_size[gid]
  geom.normal = wp.vec3(rot[0, 2], rot[1, 2], rot[2, 2])  # plane
  dataid = m.geom_dataid[gid]
  if dataid >= 0:
    geom.vertadr = m.mesh_vertadr[dataid]
    geom.vertnum = m.mesh_vertnum[dataid]
  else:
    geom.vertadr = -1
    geom.vertnum = -1

  return geom


@wp.func
def write_contact(
  d: Data,
  dist: float,
  pos: wp.vec3,
  frame: wp.mat33,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
  worldid: int,
):
  active = (dist - margin) < 0
  if active:
    cid = wp.atomic_add(d.ncon, 0, 1)
    if cid < d.nconmax:
      d.contact.dist[cid] = dist
      d.contact.pos[cid] = pos
      d.contact.frame[cid] = frame
      d.contact.geom[cid] = geoms
      d.contact.worldid[cid] = worldid
      d.contact.includemargin[cid] = margin - gap
      d.contact.dim[cid] = condim
      d.contact.friction[cid] = friction
      d.contact.solref[cid] = solref
      d.contact.solreffriction[cid] = solreffriction
      d.contact.solimp[cid] = solimp


@wp.func
def _plane_sphere(
  plane_normal: wp.vec3, plane_pos: wp.vec3, sphere_pos: wp.vec3, sphere_radius: float
):
  dist = wp.dot(sphere_pos - plane_pos, plane_normal) - sphere_radius
  pos = sphere_pos - plane_normal * (sphere_radius + 0.5 * dist)
  return dist, pos


@wp.func
def plane_sphere(
  plane: Geom,
  sphere: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  dist, pos = _plane_sphere(plane.normal, plane.pos, sphere.pos, sphere.size[0])

  write_contact(
    d,
    dist,
    pos,
    make_frame(plane.normal),
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    worldid,
  )


@wp.func
def _sphere_sphere(
  pos1: wp.vec3,
  radius1: float,
  pos2: wp.vec3,
  radius2: float,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  dir = pos2 - pos1
  dist = wp.length(dir)
  if dist == 0.0:
    n = wp.vec3(1.0, 0.0, 0.0)
  else:
    n = dir / dist
  dist = dist - (radius1 + radius2)
  pos = pos1 + n * (radius1 + 0.5 * dist)

  write_contact(
    d,
    dist,
    pos,
    make_frame(n),
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    worldid,
  )


@wp.func
def _sphere_sphere_ext(
  pos1: wp.vec3,
  radius1: float,
  pos2: wp.vec3,
  radius2: float,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
  mat1: wp.mat33,
  mat2: wp.mat33,
):
  dir = pos2 - pos1
  dist = wp.length(dir)
  if dist == 0.0:
    # Use cross product of z axes like MuJoCo
    axis1 = wp.vec3(mat1[0, 2], mat1[1, 2], mat1[2, 2])
    axis2 = wp.vec3(mat2[0, 2], mat2[1, 2], mat2[2, 2])
    n = wp.cross(axis1, axis2)
    n = wp.normalize(n)
  else:
    n = dir / dist
  dist = dist - (radius1 + radius2)
  pos = pos1 + n * (radius1 + 0.5 * dist)

  write_contact(
    d,
    dist,
    pos,
    make_frame(n),
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    worldid,
  )


@wp.func
def sphere_sphere(
  sphere1: Geom,
  sphere2: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  _sphere_sphere(
    sphere1.pos,
    sphere1.size[0],
    sphere2.pos,
    sphere2.size[0],
    worldid,
    d,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
  )


@wp.func
def sphere_capsule(
  sphere: Geom,
  cap: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  """Calculates one contact between a sphere and a capsule."""
  axis = wp.vec3(cap.rot[0, 2], cap.rot[1, 2], cap.rot[2, 2])
  length = cap.size[1]
  segment = axis * length

  # Find closest point on capsule centerline to sphere center
  pt = closest_segment_point(cap.pos - segment, cap.pos + segment, sphere.pos)

  # Treat as sphere-sphere collision between sphere and closest point
  _sphere_sphere(
    sphere.pos,
    sphere.size[0],
    pt,
    cap.size[0],
    worldid,
    d,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
  )


@wp.func
def capsule_capsule(
  cap1: Geom,
  cap2: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  axis1 = wp.vec3(cap1.rot[0, 2], cap1.rot[1, 2], cap1.rot[2, 2])
  axis2 = wp.vec3(cap2.rot[0, 2], cap2.rot[1, 2], cap2.rot[2, 2])
  length1 = cap1.size[1]
  length2 = cap2.size[1]
  seg1 = axis1 * length1
  seg2 = axis2 * length2

  pt1, pt2 = closest_segment_to_segment_points(
    cap1.pos - seg1,
    cap1.pos + seg1,
    cap2.pos - seg2,
    cap2.pos + seg2,
  )

  _sphere_sphere(
    pt1,
    cap1.size[0],
    pt2,
    cap2.size[0],
    worldid,
    d,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
  )


@wp.func
def plane_capsule(
  plane: Geom,
  cap: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  """Calculates two contacts between a capsule and a plane."""
  n = plane.normal
  axis = wp.vec3(cap.rot[0, 2], cap.rot[1, 2], cap.rot[2, 2])
  # align contact frames with capsule axis
  b, b_norm = normalize_with_norm(axis - n * wp.dot(n, axis))

  if b_norm < 0.5:
    if -0.5 < n[1] and n[1] < 0.5:
      b = wp.vec3(0.0, 1.0, 0.0)
    else:
      b = wp.vec3(0.0, 0.0, 1.0)

  c = wp.cross(n, b)
  frame = wp.mat33(n[0], n[1], n[2], b[0], b[1], b[2], c[0], c[1], c[2])
  segment = axis * cap.size[1]

  dist1, pos1 = _plane_sphere(n, plane.pos, cap.pos + segment, cap.size[0])
  write_contact(
    d,
    dist1,
    pos1,
    frame,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    worldid,
  )

  dist2, pos2 = _plane_sphere(n, plane.pos, cap.pos - segment, cap.size[0])
  write_contact(
    d,
    dist2,
    pos2,
    frame,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    worldid,
  )


@wp.func
def plane_box(
  plane: Geom,
  box: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  count = int(0)
  corner = wp.vec3()
  dist = wp.dot(box.pos - plane.pos, plane.normal)

  # test all corners, pick bottom 4
  for i in range(8):
    # get corner in local coordinates
    corner.x = wp.where(i & 1, box.size.x, -box.size.x)
    corner.y = wp.where(i & 2, box.size.y, -box.size.y)
    corner.z = wp.where(i & 4, box.size.z, -box.size.z)

    # get corner in global coordinates relative to box center
    corner = box.rot * corner

    # compute distance to plane, skip if too far or pointing up
    ldist = wp.dot(plane.normal, corner)
    if dist + ldist > margin or ldist > 0:
      continue

    cdist = dist + ldist
    frame = make_frame(plane.normal)
    pos = corner + box.pos + (plane.normal * cdist / -2.0)
    write_contact(
      d,
      cdist,
      pos,
      frame,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      worldid,
    )
    count += 1
    if count >= 4:
      break


@wp.func
def sphere_cylinder(
  sphere: Geom,
  cylinder: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  axis = wp.vec3(
    cylinder.rot[0, 2],
    cylinder.rot[1, 2],
    cylinder.rot[2, 2],
  )

  vec = sphere.pos - cylinder.pos
  x = wp.dot(vec, axis)

  a_proj = axis * x
  p_proj = vec - a_proj
  p_proj_sqr = wp.dot(p_proj, p_proj)

  collide_side = wp.abs(x) < cylinder.size[1]
  collide_cap = p_proj_sqr < (cylinder.size[0] * cylinder.size[0])

  if collide_side and collide_cap:
    dist_cap = cylinder.size[1] - wp.abs(x)
    dist_radius = cylinder.size[0] - wp.sqrt(p_proj_sqr)

    if dist_cap < dist_radius:
      collide_side = False
    else:
      collide_cap = False

  # Side collision
  if collide_side:
    pos_target = cylinder.pos + a_proj
    _sphere_sphere_ext(
      sphere.pos,
      sphere.size[0],
      pos_target,
      cylinder.size[0],
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      sphere.rot,
      cylinder.rot,
    )
    return

  # Cap collision
  if collide_cap:
    if x > 0.0:
      # top cap
      pos_cap = cylinder.pos + axis * cylinder.size[1]
      plane_normal = axis
    else:
      # bottom cap
      pos_cap = cylinder.pos - axis * cylinder.size[1]
      plane_normal = -axis

    dist, pos_contact = _plane_sphere(plane_normal, pos_cap, sphere.pos, sphere.size[0])
    plane_normal = -plane_normal  # Flip normal after position calculation

    write_contact(
      d,
      dist,
      pos_contact,
      make_frame(plane_normal),
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      worldid,
    )

    return

  # Corner collision
  inv_len = 1.0 / wp.sqrt(p_proj_sqr)
  p_proj = p_proj * (cylinder.size[0] * inv_len)

  cap_offset = axis * (wp.sign(x) * cylinder.size[1])
  pos_corner = cylinder.pos + cap_offset + p_proj

  _sphere_sphere_ext(
    sphere.pos,
    sphere.size[0],
    pos_corner,
    0.0,
    worldid,
    d,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    sphere.rot,
    cylinder.rot,
  )


@wp.func
def plane_cylinder(
  plane: Geom,
  cylinder: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  """Calculates contacts between a cylinder and a plane."""
  # Extract plane normal and cylinder axis
  n = plane.normal
  axis = wp.vec3(cylinder.rot[0, 2], cylinder.rot[1, 2], cylinder.rot[2, 2])

  # Project, make sure axis points toward plane
  prjaxis = wp.dot(n, axis)
  if prjaxis > 0:
    axis = -axis
    prjaxis = -prjaxis

  # Compute normal distance from plane to cylinder center
  dist0 = wp.dot(cylinder.pos - plane.pos, n)

  # Remove component of -normal along cylinder axis
  vec = axis * prjaxis - n
  len_sqr = wp.dot(vec, vec)

  # If vector is nondegenerate, normalize and scale by radius
  # Otherwise use cylinder's x-axis scaled by radius
  vec = wp.where(
    len_sqr >= 1e-12,
    vec * (cylinder.size[0] / wp.sqrt(len_sqr)),
    wp.vec3(cylinder.rot[0, 0], cylinder.rot[1, 0], cylinder.rot[2, 0])
    * cylinder.size[0],
  )

  # Project scaled vector on normal
  prjvec = wp.dot(vec, n)

  # Scale cylinder axis by half-length
  axis = axis * cylinder.size[1]
  prjaxis = prjaxis * cylinder.size[1]

  frame = make_frame(n)

  # First contact point (end cap closer to plane)
  dist1 = dist0 + prjaxis + prjvec
  if dist1 <= margin:
    pos1 = cylinder.pos + vec + axis - n * (dist1 * 0.5)
    write_contact(
      d,
      dist1,
      pos1,
      frame,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      worldid,
    )
  else:
    # If nearest point is above margin, no contacts
    return

  # Second contact point (end cap farther from plane)
  dist2 = dist0 - prjaxis + prjvec
  if dist2 <= margin:
    pos2 = cylinder.pos + vec - axis - n * (dist2 * 0.5)
    write_contact(
      d,
      dist2,
      pos2,
      frame,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      worldid,
    )

  # Try triangle contact points on side closer to plane
  prjvec1 = -prjvec * 0.5
  dist3 = dist0 + prjaxis + prjvec1
  if dist3 <= margin:
    # Compute sideways vector scaled by radius*sqrt(3)/2
    vec1 = wp.cross(vec, axis)
    vec1 = wp.normalize(vec1) * (cylinder.size[0] * wp.sqrt(3.0) * 0.5)

    # Add contact point A - adjust to closest side
    pos3 = cylinder.pos + vec1 + axis - vec * 0.5 - n * (dist3 * 0.5)
    write_contact(
      d,
      dist3,
      pos3,
      frame,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      worldid,
    )

    # Add contact point B - adjust to closest side
    pos4 = cylinder.pos - vec1 + axis - vec * 0.5 - n * (dist3 * 0.5)
    write_contact(
      d,
      dist3,
      pos4,
      frame,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
      worldid,
    )


@wp.func
def contact_params(m: Model, d: Data, cid: int):
  geoms = d.collision_pair[cid]
  pairid = d.collision_pairid[cid]

  if pairid > -1:
    margin = m.pair_margin[pairid]
    gap = m.pair_gap[pairid]
    condim = m.pair_dim[pairid]
    friction = m.pair_friction[pairid]
    solref = m.pair_solref[pairid]
    solreffriction = m.pair_solreffriction[pairid]
    solimp = m.pair_solimp[pairid]
  else:
    g1 = geoms[0]
    g2 = geoms[1]

    p1 = m.geom_priority[g1]
    p2 = m.geom_priority[g2]

    solmix1 = m.geom_solmix[g1]
    solmix2 = m.geom_solmix[g2]

    mix = solmix1 / (solmix1 + solmix2)
    mix = wp.where((solmix1 < MJ_MINVAL) and (solmix2 < MJ_MINVAL), 0.5, mix)
    mix = wp.where((solmix1 < MJ_MINVAL) and (solmix2 >= MJ_MINVAL), 0.0, mix)
    mix = wp.where((solmix1 >= MJ_MINVAL) and (solmix2 < MJ_MINVAL), 1.0, mix)
    mix = wp.where(p1 == p2, mix, wp.where(p1 > p2, 1.0, 0.0))

    margin = wp.max(m.geom_margin[g1], m.geom_margin[g2])
    gap = wp.max(m.geom_gap[g1], m.geom_gap[g2])

    condim1 = m.geom_condim[g1]
    condim2 = m.geom_condim[g2]
    condim = wp.where(
      p1 == p2, wp.max(condim1, condim2), wp.where(p1 > p2, condim1, condim2)
    )

    geom_friction = wp.max(m.geom_friction[g1], m.geom_friction[g2])
    friction = vec5(
      geom_friction[0],
      geom_friction[0],
      geom_friction[1],
      geom_friction[2],
      geom_friction[2],
    )

    if m.geom_solref[g1].x > 0.0 and m.geom_solref[g2].x > 0.0:
      solref = mix * m.geom_solref[g1] + (1.0 - mix) * m.geom_solref[g2]
    else:
      solref = wp.min(m.geom_solref[g1], m.geom_solref[g2])

    solreffriction = wp.vec2(0.0, 0.0)

    solimp = mix * m.geom_solimp[g1] + (1.0 - mix) * m.geom_solimp[g2]

  return geoms, margin, gap, condim, friction, solref, solreffriction, solimp


@wp.func
def _sphere_box(
  sphere_pos: wp.vec3,
  sphere_size: float,
  box_pos: wp.vec3,
  box_rot: wp.mat33,
  box_size: wp.vec3,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  center = wp.transpose(box_rot) @ (sphere_pos - box_pos)

  clamped = wp.max(-box_size, wp.min(box_size, center))
  clamped_dir, dist = normalize_with_norm(clamped - center)

  if dist - sphere_size > margin:
    return

  # sphere center inside box
  if dist <= MJ_MINVAL:
    closest = 2.0 * (box_size[0] + box_size[1] + box_size[2])
    k = wp.int32(0)
    for i in range(6):
      face_dist = wp.abs(wp.where(i % 2, 1.0, -1.0) * box_size[i / 2] - center[i / 2])
      if closest > face_dist:
        closest = face_dist
        k = i

    nearest = wp.vec3(0.0)
    nearest[k / 2] = wp.where(k % 2, -1.0, 1.0)
    pos = center + nearest * (sphere_size - closest) / 2.0
    contact_normal = box_rot @ nearest
    contact_dist = -closest - sphere_size

  else:
    deepest = center + clamped_dir * sphere_size
    pos = 0.5 * (clamped + deepest)
    contact_normal = box_rot @ clamped_dir
    contact_dist = dist - sphere_size

  contact_pos = box_pos + box_rot @ pos
  write_contact(
    d,
    contact_dist,
    contact_pos,
    make_frame(contact_normal),
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
    worldid,
  )


@wp.func
def sphere_box(
  sphere: Geom,
  box: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  _sphere_box(
    sphere.pos,
    sphere.size[0],
    box.pos,
    box.rot,
    box.size,
    worldid,
    d,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
  )


@wp.func
def capsule_box(
  cap: Geom,
  box: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  """Calculates contacts between a capsule and a box."""
  # Based on the mjc implementation
  pos = wp.transpose(box.rot) @ (cap.pos - box.pos)
  axis = wp.vec3(cap.rot[0, 2], cap.rot[1, 2], cap.rot[2, 2])
  halfaxis = axis * cap.size[1]  # halfaxis is the capsule direction
  axisdir = (
    wp.int32(axis[0] > 0.0) + 2 * wp.int32(axis[1] > 0.0) + 4 * wp.int32(axis[2] > 0.0)
  )

  bestdistmax = margin + 2.0 * (
    cap.size[0] + cap.size[1] + box.size[0] + box.size[1] + box.size[2]
  )

  # keep track of closest point
  bestdist = wp.float32(bestdistmax)
  bestsegmentpos = wp.float32(-12)

  # cltype: encoded collision configuration
  # cltype / 3 == 0 : lower corner is closest to the capsule
  #            == 2 : upper corner is closest to the capsule
  #            == 1 : middle of the edge is closest to the capsule
  # cltype % 3 == 0 : lower corner is closest to the box
  #            == 2 : upper corner is closest to the box
  #            == 1 : middle of the capsule is closest to the box
  cltype = wp.int32(-4)

  # clface: index of the closest face of the box to the capsule
  # -1: no face is closest (edge or corner is closest)
  # 0, 1, 2: index of the axis perpendicular to the closest face
  clface = wp.int32(-12)

  # first: consider cases where a face of the box is closest
  for i in range(-1, 2, 2):
    axisTip = pos + wp.float32(i) * halfaxis
    boxPoint = wp.vec3(axisTip)

    n_out = wp.int32(0)
    ax_out = wp.int32(-1)

    for j in range(3):
      if boxPoint[j] < -box.size[j]:
        n_out += 1
        ax_out = j
        boxPoint[j] = -box.size[j]
      elif boxPoint[j] > box.size[j]:
        n_out += 1
        ax_out = j
        boxPoint[j] = box.size[j]

    if n_out > 1:
      continue

    dist = wp.length_sq(boxPoint - axisTip)

    if dist < bestdist:
      bestdist = dist
      bestsegmentpos = wp.float32(i)
      cltype = -2 + i
      clface = ax_out

  # second: consider cases where an edge of the box is closest
  clcorner = wp.int32(-123)  # which corner is the closest
  cledge = wp.int32(-123)  # which axis
  bestboxpos = wp.float32(0.0)

  for i in range(8):
    for j in range(3):
      if i & (1 << j) != 0:
        continue

      c2 = wp.int32(-123)

      # box_pt is the starting point (corner) on the box
      box_pt = wp.cw_mul(
        wp.vec3(
          wp.where(i & 1, 1.0, -1.0),
          wp.where(i & 2, 1.0, -1.0),
          wp.where(i & 4, 1.0, -1.0),
        ),
        box.size,
      )
      box_pt[j] = 0.0

      # find closest point between capsule and the edge
      dif = box_pt - pos

      u = -box.size[j] * dif[j]
      v = wp.dot(halfaxis, dif)
      ma = box.size[j] * box.size[j]
      mb = -box.size[j] * halfaxis[j]
      mc = cap.size[1] * cap.size[1]
      det = ma * mc - mb * mb
      if wp.abs(det) < MJ_MINVAL:
        continue

      idet = 1.0 / det
      # sX : X=1 means middle of segment. X=0 or 2 one or the other end

      x1 = wp.float32((mc * u - mb * v) * idet)
      x2 = wp.float32((ma * v - mb * u) * idet)

      s1 = wp.int32(1)
      s2 = wp.int32(1)

      if x1 > 1:
        x1 = 1.0
        s1 = 2
        x2 = (v - mb) / mc
      elif x1 < -1:
        x1 = -1.0
        s1 = 0
        x2 = (v + mb) / mc

      x2_over = x2 > 1.0
      if x2_over or x2 < -1.0:
        if x2_over:
          x2 = 1.0
          s2 = 2
          x1 = (u - mb) / ma
        else:
          x2 = -1.0
          s2 = 0
          x1 = (u + mb) / ma

        if x1 > 1:
          x1 = 1.0
          s1 = 2
        elif x1 < -1:
          x1 = -1.0
          s1 = 0

      dif -= halfaxis * x2
      dif[j] += box.size[j] * x1

      # encode relative positions of the closest points
      ct = s1 * 3 + s2

      dif_sq = wp.length_sq(dif)
      if dif_sq < bestdist - MJ_MINVAL:
        bestdist = dif_sq
        bestsegmentpos = x2
        bestboxpos = x1
        # ct<6 means closest point on box is at lower end or middle of edge
        c2 = ct / 6

        clcorner = i + (1 << j) * c2  # index of closest box corner
        cledge = j  # axis index of closest box edge
        cltype = ct  # encoded collision configuration

  best = wp.float32(0.0)
  l = wp.float32(0.0)

  p = wp.vec2(pos.x, pos.y)
  dd = wp.vec2(halfaxis.x, halfaxis.y)
  s = wp.vec2(box.size.x, box.size.y)
  secondpos = wp.float32(-4.0)

  l = wp.length_sq(dd)

  uu = dd.x * s.y
  vv = dd.y * s.x
  w_neg = dd.x * p.y - dd.y * p.x < 0

  best = wp.float32(-1.0)

  ee1 = uu - vv
  ee2 = uu + vv

  if wp.abs(ee1) > best:
    best = wp.abs(ee1)
    c1 = wp.where((ee1 < 0) == w_neg, 0, 3)

  if wp.abs(ee2) > best:
    best = wp.abs(ee2)
    c1 = wp.where((ee2 > 0) == w_neg, 1, 2)

  if cltype == -4:  # invalid type
    return

  if cltype >= 0 and cltype / 3 != 1:  # closest to a corner of the box
    c1 = axisdir ^ clcorner
    # Calculate relative orientation between capsule and corner
    # There are two possible configurations:
    # 1. Capsule axis points toward/away from corner
    # 2. Capsule axis aligns with a face or edge
    if c1 != 0 and c1 != 7:  # create second contact point
      if c1 == 1 or c1 == 2 or c1 == 4:
        mul = 1
      else:
        mul = -1
        c1 = 7 - c1

      # "de" and "dp" distance from first closest point on the capsule to both ends of it
      # mul is a direction along the capsule's axis

      if c1 == 1:
        ax = 0
        ax1 = 1
        ax2 = 2
      elif c1 == 2:
        ax = 1
        ax1 = 2
        ax2 = 0
      elif c1 == 4:
        ax = 2
        ax1 = 0
        ax2 = 1

      if axis[ax] * axis[ax] > 0.5:  # second point along the edge of the box
        m = 2.0 * box.size[ax] / wp.abs(halfaxis[ax])
        secondpos = min(1.0 - wp.float32(mul) * bestsegmentpos, m)
      else:  # second point along a face of the box
        # check for overshoot again
        m = 2.0 * min(
          box.size[ax1] / wp.abs(halfaxis[ax1]), box.size[ax2] / wp.abs(halfaxis[ax2])
        )
        secondpos = -min(1.0 + wp.float32(mul) * bestsegmentpos, m)
      secondpos *= wp.float32(mul)

  elif cltype >= 0 and cltype / 3 == 1:  # we are on box's edge
    # Calculate relative orientation between capsule and edge
    # Two possible configurations:
    # - T configuration: c1 = 2^n (no additional contacts)
    # - X configuration: c1 != 2^n (potential additional contacts)
    c1 = axisdir ^ clcorner
    c1 &= 7 - (1 << cledge)  # mask out edge axis to determine configuration

    if c1 == 1 or c1 == 2 or c1 == 4:  # create second contact point
      if cledge == 0:
        ax1 = 1
        ax2 = 2
      if cledge == 1:
        ax1 = 2
        ax2 = 0
      if cledge == 2:
        ax1 = 0
        ax2 = 1
      ax = cledge

      # Then it finds with which face the capsule has a lower angle and switches the axis names
      if wp.abs(axis[ax1]) > wp.abs(axis[ax2]):
        ax1 = ax2
      ax2 = 3 - ax - ax1

      # mul determines direction along capsule axis for second contact point
      if c1 & (1 << ax2):
        mul = 1
        secondpos = 1.0 - bestsegmentpos
      else:
        mul = -1
        secondpos = 1.0 + bestsegmentpos

      # now we have to find out whether we point towards the opposite side or towards one of the
      # sides and also find the farthest point along the capsule that is above the box

      e1 = 2.0 * box.size[ax2] / wp.abs(halfaxis[ax2])
      secondpos = min(e1, secondpos)

      if ((axisdir & (1 << ax)) != 0) == ((c1 & (1 << ax2)) != 0):
        e2 = 1.0 - bestboxpos
      else:
        e2 = 1.0 + bestboxpos

      e1 = box.size[ax] * e2 / wp.abs(halfaxis[ax])

      secondpos = min(e1, secondpos)
      secondpos *= wp.float32(mul)

  elif cltype < 0:
    # similarly we handle the case when one capsule's end is closest to a face of the box
    # and find where is the other end pointing to and clamping to the farthest point
    # of the capsule that's above the box
    # if the closest point is inside the box there's no need for a second point

    if clface != -1:  # create second contact point
      mul = wp.where(cltype == -3, 1, -1)
      secondpos = 2.0

      tmp1 = pos - halfaxis * wp.float32(mul)

      for i in range(3):
        if i != clface:
          ha_r = wp.float32(mul) / halfaxis[i]
          e1 = (box.size[i] - tmp1[i]) * ha_r
          if 0 < e1 and e1 < secondpos:
            secondpos = e1

          e1 = (-box.size[i] - tmp1[i]) * ha_r
          if 0 < e1 and e1 < secondpos:
            secondpos = e1

      secondpos *= wp.float32(mul)

  # create sphere in original orientation at first contact point
  s1_pos_l = pos + halfaxis * bestsegmentpos
  s1_pos_g = box.rot @ s1_pos_l + box.pos

  # collide with sphere
  _sphere_box(
    s1_pos_g,
    cap.size[0],
    box.pos,
    box.rot,
    box.size,
    worldid,
    d,
    margin,
    gap,
    condim,
    friction,
    solref,
    solreffriction,
    solimp,
    geoms,
  )

  if secondpos > -3:  # secondpos was modified
    s2_pos_l = pos + halfaxis * (secondpos + bestsegmentpos)
    s2_pos_g = box.rot @ s2_pos_l + box.pos
    _sphere_box(
      s2_pos_g,
      cap.size[0],
      box.pos,
      box.rot,
      box.size,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )


@wp.func
def compute_rotmore(face_idx: wp.int32) -> wp.mat33:
  rotmore = wp.mat33(0.0)

  if face_idx == 0:
    rotmore[0, 2] = -1.0
    rotmore[1, 1] = +1.0
    rotmore[2, 0] = +1.0
  elif face_idx == 1:
    rotmore[0, 0] = +1.0
    rotmore[1, 2] = -1.0
    rotmore[2, 1] = +1.0
  elif face_idx == 2:
    rotmore[0, 0] = +1.0
    rotmore[1, 1] = +1.0
    rotmore[2, 2] = +1.0
  elif face_idx == 3:
    rotmore[0, 2] = +1.0
    rotmore[1, 1] = +1.0
    rotmore[2, 0] = -1.0
  elif face_idx == 4:
    rotmore[0, 0] = +1.0
    rotmore[1, 2] = +1.0
    rotmore[2, 1] = -1.0
  elif face_idx == 5:
    rotmore[0, 0] = -1.0
    rotmore[1, 1] = +1.0
    rotmore[2, 2] = -1.0

  return rotmore


@wp.func
def box_box(
  box1: Geom,
  box2: Geom,
  worldid: int,
  d: Data,
  margin: float,
  gap: float,
  condim: int,
  friction: vec5,
  solref: wp.vec2f,
  solreffriction: wp.vec2f,
  solimp: vec5,
  geoms: wp.vec2i,
):
  # Compute transforms between box's frames

  pos21 = wp.transpose(box1.rot) @ (box2.pos - box1.pos)
  pos12 = wp.transpose(box2.rot) @ (box1.pos - box2.pos)

  rot21 = wp.transpose(box1.rot) @ box2.rot
  rot12 = wp.transpose(rot21)

  rot21abs = wp.matrix_from_rows(wp.abs(rot21[0]), wp.abs(rot21[1]), wp.abs(rot21[2]))
  rot12abs = wp.transpose(rot21abs)

  plen2 = rot21abs @ box2.size
  plen1 = rot12abs @ box1.size

  # Compute axis of maximum separation
  s_sum_3 = 3.0 * (box1.size + box2.size)
  separation = wp.float32(margin + s_sum_3[0] + s_sum_3[1] + s_sum_3[2])
  axis_code = wp.int32(-1)

  # First test: consider boxes' face normals
  for i in range(3):
    c1 = -wp.abs(pos21[i]) + box1.size[i] + plen2[i]

    c2 = -wp.abs(pos12[i]) + box2.size[i] + plen1[i]

    if c1 < -margin or c2 < -margin:
      return

    if c1 < separation:
      separation = c1
      axis_code = i + 3 * wp.int32(pos21[i] < 0) + 0  # Face of box1
    if c2 < separation:
      separation = c2
      axis_code = i + 3 * wp.int32(pos12[i] < 0) + 6  # Face of box2

  clnorm = wp.vec3(0.0)
  inv = wp.bool(False)
  cle1 = wp.int32(0)
  cle2 = wp.int32(0)

  # Second test: consider cross products of boxes' edges
  for i in range(3):
    for j in range(3):
      # Compute cross product of box edges (potential separating axis)
      if i == 0:
        cross_axis = wp.vec3(0.0, -rot12[j, 2], rot12[j, 1])
      elif i == 1:
        cross_axis = wp.vec3(rot12[j, 2], 0.0, -rot12[j, 0])
      else:
        cross_axis = wp.vec3(-rot12[j, 1], rot12[j, 0], 0.0)

      cross_length = wp.length(cross_axis)
      if cross_length < MJ_MINVAL:
        continue

      cross_axis /= cross_length

      box_dist = wp.dot(pos21, cross_axis)
      c3 = wp.float32(0.0)

      # Project box half-sizes onto the potential separating axis
      for k in range(3):
        if k != i:
          c3 += box1.size[k] * wp.abs(cross_axis[k])
        if k != j:
          c3 += box2.size[k] * rot21abs[i, 3 - k - j] / cross_length

      c3 -= wp.abs(box_dist)

      # Early exit: no collision if separated along this axis
      if c3 < -margin:
        return

      # Track minimum separation and which edge-edge pair it occurs on
      if c3 < separation * (1.0 - 1e-12):
        separation = c3
        # Determine which corners/edges are closest
        cle1 = 0
        cle2 = 0

        for k in range(3):
          if k != i and (int(cross_axis[k] > 0) ^ int(box_dist < 0)):
            cle1 += 1 << k
          if k != j and (
            int(rot21[i, 3 - k - j] > 0) ^ int(box_dist < 0) ^ int((k - j + 3) % 3 == 1)
          ):
            cle2 += 1 << k

        axis_code = 12 + i * 3 + j
        clnorm = cross_axis
        inv = box_dist < 0

  # No axis with separation < margin found
  if axis_code == -1:
    return

  points = mat83f()
  depth = vec8f()
  max_con_pair = 8
  # 8 contacts should suffice for most configurations

  if axis_code < 12:
    # Handle face-vertex collision
    face_idx = axis_code % 6
    box_idx = axis_code / 6
    rotmore = compute_rotmore(face_idx)

    r = rotmore @ wp.where(box_idx, rot12, rot21)
    p = rotmore @ wp.where(box_idx, pos12, pos21)
    ss = wp.abs(rotmore @ wp.where(box_idx, box2.size, box1.size))
    s = wp.where(box_idx, box1.size, box2.size)
    rt = wp.transpose(r)

    lx, ly, hz = ss[0], ss[1], ss[2]
    p[2] -= hz

    clcorner = wp.int32(0)  # corner of non-face box with least axis separation

    for i in range(3):
      if r[2, i] < 0:
        clcorner += 1 << i

    lp = p
    for i in range(wp.static(3)):
      lp += rt[i] * s[i] * wp.where(clcorner & 1 << i, 1.0, -1.0)

    m = wp.int32(1)
    dirs = wp.int32(0)

    cn1 = wp.vec3(0.0)
    cn2 = wp.vec3(0.0)

    for i in range(3):
      if wp.abs(r[2, i]) < 0.5:
        if not dirs:
          cn1 = rt[i] * s[i] * wp.where(clcorner & (1 << i), -2.0, 2.0)
        else:
          cn2 = rt[i] * s[i] * wp.where(clcorner & (1 << i), -2.0, 2.0)

        dirs += 1

    k = dirs * dirs

    # Find potential contact points
    lines_a = mat43f()
    lines_b = mat43f()

    if dirs:
      lines_a[0] = lp
      lines_b[0] = cn1

    if dirs == 2:
      lines_a[1] = lp
      lines_b[1] = cn2

      lines_a[2] = lp + cn1
      lines_b[2] = cn2

      lines_a[3] = lp + cn2
      lines_b[3] = cn1

    n = wp.int32(0)

    for i in range(k):
      for q in range(2):
        la = lines_a[i, q]
        lb = lines_b[i, q]
        lc = lines_a[i, 1 - q]
        ld = lines_b[i, 1 - q]

        if wp.abs(lb) > MJ_MINVAL:
          br = 1.0 / lb
          for j in range(-1, 2, 2):
            l = ss[q] * wp.float32(j)
            c1 = (l - la) * br
            if c1 < 0 or c1 > 1:
              continue
            c2 = lc + ld * c1
            if wp.abs(c2) > ss[1 - q]:
              continue

            points[n] = lines_a[i] + c1 * lines_b[i]
            n += 1

    if dirs == 2:
      ax = cn1[0]
      bx = cn2[0]
      ay = cn1[1]
      by = cn2[1]
      C = 1.0 / (ax * by - bx * ay)

      for i in range(4):
        llx = wp.where(i / 2, lx, -lx)
        lly = wp.where(i % 2, ly, -ly)

        x = llx - lp[0]
        y = lly - lp[1]

        u = (x * by - y * bx) * C
        v = (y * ax - x * ay) * C

        if u > 0 and v > 0 and u < 1 and v < 1:
          points[n] = wp.vec3(llx, lly, lp[2] + u * cn1[2] + v * cn2[2])
          n += 1

    for i in range(k):
      tmpv = lp + wp.float32(i & 1) * cn1 + wp.float32(i & 2) * cn2
      if tmpv[0] > -lx and tmpv[0] < lx and tmpv[1] > -ly and tmpv[1] < ly:
        points[n] = tmpv
        n += 1

    m = n
    n = wp.int32(0)

    for i in range(m):
      if points[i][2] > margin:
        continue
      if i != n:
        points[n] = points[i]

      points[n, 2] *= 0.5
      depth[n] = points[n, 2]
      n += 1

    # Set up contact frame
    rw = wp.where(box_idx, box2.rot, box1.rot) @ wp.transpose(rotmore)
    pw = wp.where(box_idx, box2.pos, box1.pos)
    normal = wp.where(box_idx, -1.0, 1.0) * wp.transpose(rw)[2]

  else:
    # Handle edge-edge collision
    edge1 = (axis_code - 12) / 3
    edge2 = (axis_code - 12) % 3

    # Set up non-contacting edges ax1, ax2 for box2 and pax1, pax2 for box 1
    ax1 = wp.int(1 - (edge2 & 1))
    ax2 = wp.int(2 - (edge2 & 2))

    pax1 = wp.int(1 - (edge1 & 1))
    pax2 = wp.int(2 - (edge1 & 2))

    if rot21abs[edge1, ax1] < rot21abs[edge1, ax2]:
      ax1, ax2 = ax2, ax1

    if rot12abs[edge2, pax1] < rot12abs[edge2, pax2]:
      pax1, pax2 = pax2, pax1

    rotmore = compute_rotmore(wp.where(cle1 & (1 << pax2), pax2, pax2 + 3))

    # Transform coordinates for edge-edge contact calculation
    p = rotmore @ pos21
    rnorm = rotmore @ clnorm
    r = rotmore @ rot21
    rt = wp.transpose(r)
    s = wp.abs(wp.transpose(rotmore) @ box1.size)

    lx, ly, hz = s[0], s[1], s[2]
    p[2] -= hz

    # Calculate closest box2 face

    points[0] = (
      p
      + rt[ax1] * box2.size[ax1] * wp.where(cle2 & (1 << ax1), 1.0, -1.0)
      + rt[ax2] * box2.size[ax2] * wp.where(cle2 & (1 << ax2), 1.0, -1.0)
    )
    points[1] = points[0] - rt[edge2] * box2.size[edge2]
    points[0] += rt[edge2] * box2.size[edge2]

    points[2] = (
      p
      + rt[ax1] * box2.size[ax1] * wp.where(cle2 & (1 << ax1), -1.0, 1.0)
      + rt[ax2] * box2.size[ax2] * wp.where(cle2 & (1 << ax2), 1.0, -1.0)
    )

    points[3] = points[2] - rt[edge2] * box2.size[edge2]
    points[2] += rt[edge2] * box2.size[edge2]

    n = 4

    # Set up coordinate axes for contact face of box2
    axi_lp = points[0]
    axi_cn1 = points[1] - points[0]
    axi_cn2 = points[2] - points[0]

    # Check if contact normal is valid
    if wp.abs(rnorm[2]) < MJ_MINVAL:
      return  # Shouldn't happen

    # Calculate inverse normal for projection
    innorm = wp.where(inv, -1.0, 1.0) / rnorm[2]

    pu = mat43f()

    # Project points onto contact plane
    for i in range(4):
      pu[i] = points[i]
      c_scl = points[i, 2] * wp.where(inv, -1.0, 1.0) * innorm
      points[i] -= rnorm * c_scl

    pts_lp = points[0]
    pts_cn1 = points[1] - points[0]
    pts_cn2 = points[2] - points[0]

    lines_a = mat43f()
    lines_b = mat43f()
    linesu_a = mat43f()
    linesu_b = mat43f()

    lines_a[0] = pts_lp
    lines_b[0] = pts_cn1
    linesu_a[0] = axi_lp
    linesu_b[0] = axi_cn1

    lines_a[1] = pts_lp
    lines_b[1] = pts_cn2
    linesu_a[1] = axi_lp
    linesu_b[1] = axi_cn2

    lines_a[2] = pts_lp + pts_cn1
    lines_b[2] = pts_cn2
    linesu_a[2] = axi_lp + axi_cn1
    linesu_b[2] = axi_cn2

    lines_a[3] = pts_lp + pts_cn2
    lines_b[3] = pts_cn1
    linesu_a[3] = axi_lp + axi_cn2
    linesu_b[3] = axi_cn1

    n = wp.int32(0)

    for i in range(4):
      for q in range(2):
        la = lines_a[i, q]
        lb = lines_b[i, q]
        lc = lines_a[i, 1 - q]
        ld = lines_b[i, 1 - q]

        if wp.abs(lb) > MJ_MINVAL:
          br = 1.0 / lb
          for j in range(-1, 2, 2):
            if n == max_con_pair:
              break
            l = s[q] * wp.float32(j)
            c1 = (l - la) * br
            if c1 < 0 or c1 > 1:
              continue
            c2 = lc + ld * c1
            if wp.abs(c2) > s[1 - q]:
              continue
            if (linesu_a[i, 2] + linesu_b[i][2] * c1) * innorm > margin:
              continue

            points[n] = linesu_a[i] * 0.5 + c1 * linesu_b[i] * 0.5
            points[n, q] += 0.5 * l
            points[n, 1 - q] += 0.5 * c2
            depth[n] = points[n, 2] * innorm * 2.0
            n += 1

    nl = n

    ax = pts_cn1[0]
    bx = pts_cn2[0]
    ay = pts_cn1[1]
    by = pts_cn2[1]
    C = 1.0 / (ax * by - bx * ay)

    for i in range(4):
      if n == max_con_pair:
        break
      llx = wp.where(i / 2, lx, -lx)
      lly = wp.where(i % 2, ly, -ly)

      x = llx - pts_lp[0]
      y = lly - pts_lp[1]

      u = (x * by - y * bx) * C
      v = (y * ax - x * ay) * C

      if nl == 0:
        if (u < 0 or u > 0) and (v < 0 or v > 1):
          continue
      elif u < 0 or v < 0 or u > 1 or v > 1:
        continue

      u = wp.clamp(u, 0.0, 1.0)
      v = wp.clamp(v, 0.0, 1.0)
      w = 1.0 - u - v
      vtmp = pu[0] * w + pu[1] * u + pu[2] * v

      points[n] = wp.vec3(llx, lly, 0.0)

      vtmp2 = points[n] - vtmp
      tc1 = wp.length_sq(vtmp2)
      if vtmp[2] > 0 and tc1 > margin * margin:
        continue

      points[n] = 0.5 * (points[n] + vtmp)

      depth[n] = wp.sqrt(tc1) * wp.where(vtmp[2] < 0, -1.0, 1.0)
      n += 1

    nf = n

    for i in range(4):
      if n >= max_con_pair:
        break
      x = pu[i, 0]
      y = pu[i, 1]
      if nl == 0 and nf != 0:
        if (x < -lx or x > lx) and (y < -ly or y > ly):
          continue
      elif x < -lx or x > lx or y < -ly or y > ly:
        continue

      c1 = wp.float32(0)

      for j in range(2):
        if pu[i, j] < -s[j]:
          c1 += (pu[i, j] + s[j]) * (pu[i, j] + s[j])
        elif pu[i, j] > s[j]:
          c1 += (pu[i, j] - s[j]) * (pu[i, j] - s[j])

      c1 += pu[i, 2] * innorm * pu[i, 2] * innorm

      if pu[i, 2] > 0 and c1 > margin * margin:
        continue

      tmp_p = wp.vec3(pu[i, 0], pu[i, 1], 0.0)

      for j in range(2):
        if pu[i, j] < -s[j]:
          tmp_p[j] = -s[j] * 0.5
        elif pu[i, j] > s[j]:
          tmp_p[j] = +s[j] * 0.5

      tmp_p += pu[i]
      points[n] = tmp_p * 0.5

      depth[n] = wp.sqrt(c1) * wp.where(pu[i, 2] < 0, -1.0, 1.0)
      n += 1

    # Set up contact data for all points
    rw = box1.rot @ wp.transpose(rotmore)
    pw = box1.pos
    normal = wp.where(inv, -1.0, 1.0) * rw @ rnorm

  frame = make_frame(normal)
  coff = wp.atomic_add(d.ncon, 0, n)

  for i in range(min(d.nconmax - coff, n)):
    points[i, 2] += hz
    pos = rw @ points[i] + pw

    cid = coff + i

    d.contact.dist[cid] = depth[i]
    d.contact.pos[cid] = pos
    d.contact.frame[cid] = frame
    d.contact.geom[cid] = geoms
    d.contact.worldid[cid] = worldid
    d.contact.includemargin[cid] = margin - gap
    d.contact.dim[cid] = condim
    d.contact.friction[cid] = friction
    d.contact.solref[cid] = solref
    d.contact.solreffriction[cid] = solreffriction
    d.contact.solimp[cid] = solimp


@wp.kernel
def _primitive_narrowphase(
  m: Model,
  d: Data,
):
  tid = wp.tid()

  if tid >= d.ncollision[0]:
    return

  geoms, margin, gap, condim, friction, solref, solreffriction, solimp = contact_params(
    m, d, tid
  )
  g1 = geoms[0]
  g2 = geoms[1]

  worldid = d.collision_worldid[tid]

  geom1 = _geom(g1, m, d.geom_xpos[worldid], d.geom_xmat[worldid])
  geom2 = _geom(g2, m, d.geom_xpos[worldid], d.geom_xmat[worldid])

  type1 = m.geom_type[g1]
  type2 = m.geom_type[g2]

  # TODO(team): static loop unrolling to remove unnecessary branching
  if type1 == int(GeomType.PLANE.value) and type2 == int(GeomType.SPHERE.value):
    plane_sphere(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.SPHERE.value) and type2 == int(GeomType.SPHERE.value):
    sphere_sphere(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.PLANE.value) and type2 == int(GeomType.CAPSULE.value):
    plane_capsule(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.PLANE.value) and type2 == int(GeomType.BOX.value):
    plane_box(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.CAPSULE.value) and type2 == int(GeomType.CAPSULE.value):
    capsule_capsule(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.SPHERE.value) and type2 == int(GeomType.CAPSULE.value):
    sphere_capsule(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.SPHERE.value) and type2 == int(GeomType.CYLINDER.value):
    sphere_cylinder(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.SPHERE.value) and type2 == int(GeomType.BOX.value):
    sphere_box(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.PLANE.value) and type2 == int(GeomType.CYLINDER.value):
    plane_cylinder(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.BOX.value) and type2 == int(GeomType.BOX.value):
    box_box(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )
  elif type1 == int(GeomType.CAPSULE.value) and type2 == int(GeomType.BOX.value):
    capsule_box(
      geom1,
      geom2,
      worldid,
      d,
      margin,
      gap,
      condim,
      friction,
      solref,
      solreffriction,
      solimp,
      geoms,
    )


def primitive_narrowphase(m: Model, d: Data):
  # we need to figure out how to keep the overhead of this small - not launching anything
  # for pair types without collisions, as well as updating the launch dimensions.
  wp.launch(_primitive_narrowphase, dim=d.nconmax, inputs=[m, d])
