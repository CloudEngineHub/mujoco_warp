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

"""Tests for solver functions."""

import time
import mujoco
import numpy as np
import warp as wp
from absl.testing import absltest
from absl.testing import parameterized

import mujoco_warp as mjwarp

from . import solver
from . import test_util
from .math import safe_div
from .types import ConeType
from .types import SolverType

# tolerance for difference between MuJoCo and MJWarp solver calculations - mostly
# due to float precision
_TOLERANCE = 5e-3


def _assert_eq(a, b, name):
  tol = _TOLERANCE * 20  # avoid test noise
  err_msg = f"mismatch: {name}"
  np.testing.assert_allclose(a, b, err_msg=err_msg, atol=tol, rtol=tol)


class SolverTest(parameterized.TestCase):
  @parameterized.product(cone=tuple(ConeType), solver_=tuple(SolverType))
  def test_cost(self, cone, solver_):
    """Tests cost function is correct."""
    for keyframe in range(3):
      mjm, mjd, m, d = test_util.fixture(
        "constraints.xml",
        keyframe=keyframe,
        cone=cone,
        solver=solver_,
        iterations=0,
      )

      def cost(qacc):
        jaref = np.zeros(mjd.nefc, dtype=float)
        cost = np.zeros(1)
        mujoco.mj_mulJacVec(mjm, mjd, jaref, qacc)
        mujoco.mj_constraintUpdate(mjm, mjd, jaref - mjd.efc_aref, cost, 0)
        return cost

      mj_cost = cost(mjd.qacc)

      # solve with 0 iterations just initializes constraints and costs and then exits
      mjwarp.solve(m, d)

      mjwarp_cost = d.efc.cost.numpy()[0] - d.efc.gauss.numpy()[0]

      _assert_eq(mjwarp_cost, mj_cost, name="cost")


  @parameterized.parameters(ConeType.PYRAMIDAL, ConeType.ELLIPTIC)
  def test_init_linesearch(self, cone):
    """Test linesearch initialization."""
    mjm, mjd, m, d = test_util.fixture(
      "constraints.xml",
      cone=cone,
      iterations=0,
      ls_iterations=0,
    )

    # One step to obtain more non-zeros results
    mjwarp.step(m, d)

    # Calculate target values
    def calc_jv(njmax, efc_J, efc_search):
      jv = np.zeros(njmax)
      for i in range(njmax):
        jv[i] += np.sum(efc_J[i, :] * efc_search[:])
      return jv

    def calc_quad_gauss(efc_gauss, efc_search, efc_Ma, qfrc_smooth, efc_mv):
      quad_gauss = np.zeros(3)
      quad_gauss[0] = efc_gauss[0]
      quad_gauss[1] = np.sum(efc_search[:] * (efc_Ma[0, :] - qfrc_smooth[0, :]))
      quad_gauss[2] = 0.5 * np.sum(efc_search[:] * efc_mv[:])

      return quad_gauss

    def calc_quad(njmax, efc_jaref, efc_jv, efc_D, efc_frictionloss):
      quad = np.zeros((njmax, 3))
      for i in range(njmax):
        if efc_frictionloss[i] > 0.0:
          rf = efc_frictionloss[i] / efc_D[i]
          if efc_jaref[i] <= -rf:
            quad[i] = wp.vec3(efc_frictionloss[i] * (-0.5 * rf - efc_jaref[i]), -efc_frictionloss[i] * efc_jv[i], 0.0)
            continue
          elif efc_jaref[i] >= rf:
            quad[i] = wp.vec3(efc_frictionloss[i] * (-0.5 * rf + efc_jaref[i]), efc_frictionloss[i] * efc_jv[i], 0.0)
            continue

        quad[i, 0] = 0.5 * efc_jaref[i] * efc_jaref[i] * efc_D[i]
        quad[i, 1] = efc_jv[i] * efc_jaref[i] * efc_D[i]
        quad[i, 2] = 0.5 * efc_jv[i] * efc_jv[i] * efc_D[i]

      return quad

    def elliptic_effect(nconmax, efc_quad, efc_jv, efc_u, contact_friction, contact_dim, contact_efc_address):
      efc_uv = np.zeros(d.nconmax)
      efc_vv = np.zeros(d.nconmax)
      for i in range(nconmax):
        efcid0 = contact_efc_address[i, 0]
        for j in range(1, contact_dim[i]):
          efcid = contact_efc_address[i, j]
          efc_quad[efcid0] += efc_quad[efcid]
          u = efc_u[i, j]
          v = efc_jv[efcid] * contact_friction[i, j - 1]
          efc_uv[i] += u * v
          efc_vv[i] += v * v
      return efc_uv, efc_vv

    efc_search_np = d.efc.search.numpy()[0]
    efc_J_np = d.efc.J.numpy()
    efc_gauss_np = d.efc.gauss.numpy()
    efc_Ma_np = d.efc.Ma.numpy()
    efc_Jaref_np = d.efc.Jaref.numpy()
    efc_D_np = d.efc.D.numpy()
    efc_floss_np = d.efc.frictionloss.numpy()
    efc_u_np = d.efc.u.numpy()
    qfrc_smooth_np = d.qfrc_smooth.numpy()
    contact_friction_np = d.contact.friction.numpy()
    contact_dim_np = d.contact.dim.numpy()
    contact_efc_address_np = d.contact.efc_address.numpy()

    target_mv = np.zeros(mjm.nv)
    mujoco.mj_mulM(mjm, mjd, target_mv, efc_search_np)
    target_jv = calc_jv(d.njmax, efc_J_np, efc_search_np)
    target_quad_gauss = calc_quad_gauss(efc_gauss_np, efc_search_np, efc_Ma_np, qfrc_smooth_np, target_mv)
    target_quad = calc_quad(d.njmax, efc_Jaref_np, target_jv, efc_D_np, efc_floss_np)
    if cone == ConeType.ELLIPTIC:
      target_efc_uv, target_efc_vv = elliptic_effect(d.nconmax, target_quad, target_jv, efc_u_np, contact_friction_np, contact_dim_np, contact_efc_address_np)

    # launch linesearch with 0 iteration just doing the initialization step
    d.efc.jv.zero_()
    d.efc.quad.zero_()
    solver._linesearch(m, d)

    _assert_eq(target_mv, d.efc.mv.numpy()[0], name="efc.mv")
    _assert_eq(target_jv, d.efc.jv.numpy(), name="efc.jv")
    _assert_eq(target_quad_gauss, d.efc.quad_gauss.numpy()[0], name="efc.quad_gauss")
    _assert_eq(target_quad, d.efc.quad.numpy(), name="efc.quad")
    if cone == ConeType.ELLIPTIC:
      _assert_eq(target_efc_uv, d.efc.uv.numpy(), name="efc.uv")
      _assert_eq(target_efc_vv, d.efc.vv.numpy(), name="efc.vv")


  @parameterized.parameters(
    (ConeType.PYRAMIDAL, SolverType.CG, 5, 5, False, False),
    (ConeType.ELLIPTIC, SolverType.CG, 5, 5, False, False),
    (ConeType.PYRAMIDAL, SolverType.NEWTON, 2, 4, False, False),
    (ConeType.ELLIPTIC, SolverType.NEWTON, 2, 5, False, False),
    (ConeType.PYRAMIDAL, SolverType.NEWTON, 2, 4, True, True),
    (ConeType.ELLIPTIC, SolverType.NEWTON, 3, 16, True, True),
  )
  def test_solve(self, cone, solver_, iterations, ls_iterations, sparse, ls_parallel):
    """Tests solve."""
    for keyframe in range(3):
      mjm, mjd, m, d = test_util.fixture(
        "constraints.xml",
        keyframe=keyframe,
        sparse=sparse,
        cone=cone,
        solver=solver_,
        iterations=iterations,
        ls_iterations=ls_iterations,
        ls_parallel=ls_parallel,
      )

      qacc_warmstart = mjd.qacc_warmstart.copy()
      mujoco.mj_forward(mjm, mjd)
      mjd.qacc_warmstart = qacc_warmstart

      d.qacc.zero_()
      d.qfrc_constraint.zero_()
      d.efc.force.zero_()

      if solver_ == mujoco.mjtSolver.mjSOL_CG:
        mjwarp.factor_m(m, d)
      mjwarp.solve(m, d)

      def cost(qacc):
        jaref = np.zeros(mjd.nefc, dtype=float)
        cost = np.zeros(1)
        mujoco.mj_mulJacVec(mjm, mjd, jaref, qacc)
        mujoco.mj_constraintUpdate(mjm, mjd, jaref - mjd.efc_aref, cost, 0)
        return cost

      mj_cost = cost(mjd.qacc)
      mjwarp_cost = cost(d.qacc.numpy()[0])
      self.assertLessEqual(mjwarp_cost, mj_cost * 1.025)

      if m.opt.solver == mujoco.mjtSolver.mjSOL_NEWTON:
        _assert_eq(d.qacc.numpy()[0], mjd.qacc, "qacc")
        _assert_eq(d.qfrc_constraint.numpy()[0], mjd.qfrc_constraint, "qfrc_constraint")
        _assert_eq(d.efc.force.numpy()[: mjd.nefc], mjd.efc_force, "efc_force")

  @parameterized.parameters(
    (ConeType.PYRAMIDAL, SolverType.CG, 25, 5),
    (ConeType.PYRAMIDAL, SolverType.NEWTON, 2, 4),
  )
  def test_solve_batch(self, cone, solver_, iterations, ls_iterations):
    """Tests solve (batch)."""

    mjm0, mjd0, _, _ = test_util.fixture(
      "humanoid/humanoid.xml",
      keyframe=0,
      sparse=False,
      cone=cone,
      solver=solver_,
      iterations=iterations,
      ls_iterations=ls_iterations,
    )
    qacc_warmstart0 = mjd0.qacc_warmstart.copy()
    mujoco.mj_forward(mjm0, mjd0)
    mjd0.qacc_warmstart = qacc_warmstart0

    mjm1, mjd1, _, _ = test_util.fixture(
      "humanoid/humanoid.xml",
      keyframe=2,
      sparse=False,
      cone=cone,
      solver=solver_,
      iterations=iterations,
      ls_iterations=ls_iterations,
    )
    qacc_warmstart1 = mjd1.qacc_warmstart.copy()
    mujoco.mj_forward(mjm1, mjd1)
    mjd1.qacc_warmstart = qacc_warmstart1

    mjm2, mjd2, _, _ = test_util.fixture(
      "humanoid/humanoid.xml",
      keyframe=1,
      sparse=False,
      cone=cone,
      solver=solver_,
      iterations=iterations,
      ls_iterations=ls_iterations,
    )
    qacc_warmstart2 = mjd2.qacc_warmstart.copy()
    mujoco.mj_forward(mjm2, mjd2)
    mjd2.qacc_warmstart = qacc_warmstart2

    nefc_active = mjd0.nefc + mjd1.nefc + mjd2.nefc
    ne_active = mjd0.ne + mjd1.ne + mjd2.ne

    mjm, mjd, m, _ = test_util.fixture(
      "humanoid/humanoid.xml",
      sparse=False,
      cone=cone,
      solver=solver_,
      iterations=iterations,
      ls_iterations=ls_iterations,
    )
    d = mjwarp.put_data(mjm, mjd, nworld=3, njmax=2 * nefc_active)

    d.nefc = wp.array([nefc_active], dtype=wp.int32, ndim=1)
    d.ne = wp.array([ne_active], dtype=wp.int32, ndim=1)

    nefc_fill = d.njmax - nefc_active

    qacc_warmstart = np.vstack(
      [
        np.expand_dims(qacc_warmstart0, axis=0),
        np.expand_dims(qacc_warmstart1, axis=0),
        np.expand_dims(qacc_warmstart2, axis=0),
      ]
    )

    qM0 = np.zeros((mjm0.nv, mjm0.nv))
    mujoco.mj_fullM(mjm0, qM0, mjd0.qM)
    qM1 = np.zeros((mjm1.nv, mjm1.nv))
    mujoco.mj_fullM(mjm1, qM1, mjd1.qM)
    qM2 = np.zeros((mjm2.nv, mjm2.nv))
    mujoco.mj_fullM(mjm2, qM2, mjd2.qM)

    qM = np.vstack(
      [
        np.expand_dims(qM0, axis=0),
        np.expand_dims(qM1, axis=0),
        np.expand_dims(qM2, axis=0),
      ]
    )
    qacc_smooth = np.vstack(
      [
        np.expand_dims(mjd0.qacc_smooth, axis=0),
        np.expand_dims(mjd1.qacc_smooth, axis=0),
        np.expand_dims(mjd2.qacc_smooth, axis=0),
      ]
    )
    qfrc_smooth = np.vstack(
      [
        np.expand_dims(mjd0.qfrc_smooth, axis=0),
        np.expand_dims(mjd1.qfrc_smooth, axis=0),
        np.expand_dims(mjd2.qfrc_smooth, axis=0),
      ]
    )

    # Reshape the Jacobians
    efc_J0 = mjd0.efc_J.reshape((mjd0.nefc, mjm0.nv))
    efc_J1 = mjd1.efc_J.reshape((mjd1.nefc, mjm1.nv))
    efc_J2 = mjd2.efc_J.reshape((mjd2.nefc, mjm2.nv))

    # Extract equality constraints (first ne rows) from each world
    eq_J0 = efc_J0[: mjd0.ne]
    eq_J1 = efc_J1[: mjd1.ne]
    eq_J2 = efc_J2[: mjd2.ne]

    # Extract inequality constraints (remaining rows) from each world
    ineq_J0 = efc_J0[mjd0.ne :]
    ineq_J1 = efc_J1[mjd1.ne :]
    ineq_J2 = efc_J2[mjd2.ne :]

    # Stack all equality constraints first, then all inequality constraints
    efc_J_fill = np.vstack(
      [
        eq_J0,
        eq_J1,
        eq_J2,  # All equality constraints grouped together
        ineq_J0,
        ineq_J1,
        ineq_J2,  # All inequality constraints
        np.full((nefc_fill, mjm.nv), np.nan),  # Padding
      ]
    )

    # Similarly for D and aref values
    eq_D0 = mjd0.efc_D[: mjd0.ne]
    eq_D1 = mjd1.efc_D[: mjd1.ne]
    eq_D2 = mjd2.efc_D[: mjd2.ne]
    ineq_D0 = mjd0.efc_D[mjd0.ne :]
    ineq_D1 = mjd1.efc_D[mjd1.ne :]
    ineq_D2 = mjd2.efc_D[mjd2.ne :]

    efc_D_fill = np.concatenate([eq_D0, eq_D1, eq_D2, ineq_D0, ineq_D1, ineq_D2, np.zeros(nefc_fill)])

    eq_aref0 = mjd0.efc_aref[: mjd0.ne]
    eq_aref1 = mjd1.efc_aref[: mjd1.ne]
    eq_aref2 = mjd2.efc_aref[: mjd2.ne]
    ineq_aref0 = mjd0.efc_aref[mjd0.ne :]
    ineq_aref1 = mjd1.efc_aref[mjd1.ne :]
    ineq_aref2 = mjd2.efc_aref[mjd2.ne :]

    efc_aref_fill = np.concatenate(
      [
        eq_aref0,
        eq_aref1,
        eq_aref2,
        ineq_aref0,
        ineq_aref1,
        ineq_aref2,
        np.zeros(nefc_fill),
      ]
    )

    # World IDs need to match the new ordering
    efc_worldid = np.concatenate(
      [
        [0] * mjd0.ne,
        [1] * mjd1.ne,
        [2] * mjd2.ne,  # Equality constraints
        [0] * (mjd0.nefc - mjd0.ne),
        [1] * (mjd1.nefc - mjd1.ne),  # Inequality constraints
        [2] * (mjd2.nefc - mjd2.ne),
        [-1] * nefc_fill,  # Padding
      ]
    )

    d.qacc_warmstart = wp.from_numpy(qacc_warmstart, dtype=wp.float32)
    d.qM = wp.from_numpy(qM, dtype=wp.float32)
    d.qacc_smooth = wp.from_numpy(qacc_smooth, dtype=wp.float32)
    d.qfrc_smooth = wp.from_numpy(qfrc_smooth, dtype=wp.float32)
    d.efc.J = wp.from_numpy(efc_J_fill, dtype=wp.float32)
    d.efc.D = wp.from_numpy(efc_D_fill, dtype=wp.float32)
    d.efc.aref = wp.from_numpy(efc_aref_fill, dtype=wp.float32)
    d.efc.worldid = wp.from_numpy(efc_worldid, dtype=wp.int32)

    if solver_ == SolverType.CG:
      m0 = mjwarp.put_model(mjm0)
      d0 = mjwarp.put_data(mjm0, mjd0)
      mjwarp.factor_m(m0, d0)
      qLD0 = d0.qLD.numpy()

      m1 = mjwarp.put_model(mjm1)
      d1 = mjwarp.put_data(mjm1, mjd1)
      mjwarp.factor_m(m1, d1)
      qLD1 = d1.qLD.numpy()

      m2 = mjwarp.put_model(mjm2)
      d2 = mjwarp.put_data(mjm2, mjd2)
      mjwarp.factor_m(m2, d2)
      qLD2 = d2.qLD.numpy()

      qLD = np.vstack([qLD0, qLD1, qLD2])
      d.qLD = wp.from_numpy(qLD, dtype=wp.float32)

    d.qacc.zero_()
    d.qfrc_constraint.zero_()
    d.efc.force.zero_()
    solver.solve(m, d)

    def cost(m, d, qacc):
      jaref = np.zeros(d.nefc, dtype=float)
      cost = np.zeros(1)
      mujoco.mj_mulJacVec(m, d, jaref, qacc)
      mujoco.mj_constraintUpdate(m, d, jaref - d.efc_aref, cost, 0)
      return cost

    mj_cost0 = cost(mjm0, mjd0, mjd0.qacc)
    mjwarp_cost0 = cost(mjm0, mjd0, d.qacc.numpy()[0])
    self.assertLessEqual(mjwarp_cost0, mj_cost0 * 1.025)

    mj_cost1 = cost(mjm1, mjd1, mjd1.qacc)
    mjwarp_cost1 = cost(mjm1, mjd1, d.qacc.numpy()[1])
    self.assertLessEqual(mjwarp_cost1, mj_cost1 * 1.025)

    mj_cost2 = cost(mjm2, mjd2, mjd2.qacc)
    mjwarp_cost2 = cost(mjm2, mjd2, d.qacc.numpy()[2])
    self.assertLessEqual(mjwarp_cost2, mj_cost2 * 1.025)

    if m.opt.solver == SolverType.NEWTON:
      _assert_eq(d.qacc.numpy()[0], mjd0.qacc, "qacc0")
      _assert_eq(d.qacc.numpy()[1], mjd1.qacc, "qacc1")
      _assert_eq(d.qacc.numpy()[2], mjd2.qacc, "qacc2")

      _assert_eq(d.qfrc_constraint.numpy()[0], mjd0.qfrc_constraint, "qfrc_constraint0")
      _assert_eq(d.qfrc_constraint.numpy()[1], mjd1.qfrc_constraint, "qfrc_constraint1")
      _assert_eq(d.qfrc_constraint.numpy()[2], mjd2.qfrc_constraint, "qfrc_constraint2")

      # Get world 0 forces - equality constraints at start, inequality constraints later
      nieq0 = mjd0.nefc - mjd0.ne
      nieq1 = mjd1.nefc - mjd1.ne
      nieq2 = mjd2.nefc - mjd2.ne
      world0_eq_forces = d.efc.force.numpy()[: mjd0.ne]
      world0_ineq_forces = d.efc.force.numpy()[ne_active : ne_active + nieq0]
      world0_forces = np.concatenate([world0_eq_forces, world0_ineq_forces])
      _assert_eq(world0_forces, mjd0.efc_force, "efc_force0")

      # Get world 1 forces
      world1_eq_forces = d.efc.force.numpy()[mjd0.ne : mjd0.ne + mjd1.ne]
      world1_ineq_forces = d.efc.force.numpy()[ne_active + nieq0 : ne_active + nieq0 + nieq1]
      world1_forces = np.concatenate([world1_eq_forces, world1_ineq_forces])
      _assert_eq(world1_forces, mjd1.efc_force, "efc_force1")

      # Get world 2 forces
      world2_eq_forces = d.efc.force.numpy()[mjd0.ne + mjd1.ne : ne_active]
      world2_ineq_forces = d.efc.force.numpy()[ne_active + nieq0 + nieq1 : ne_active + nieq0 + nieq1 + nieq2]
      world2_forces = np.concatenate([world2_eq_forces, world2_ineq_forces])
      _assert_eq(world2_forces, mjd2.efc_force, "efc_force2")

  def test_frictionloss(self):
    """Tests solver with frictionloss."""
    for keyframe in range(3):
      _, mjd, m, d = test_util.fixture("constraints.xml", keyframe=keyframe)
      mjwarp.solve(m, d)

      _assert_eq(d.nf.numpy()[0], mjd.nf, "nf")
      _assert_eq(d.qacc.numpy()[0], mjd.qacc, "qacc")
      _assert_eq(d.qfrc_constraint.numpy()[0], mjd.qfrc_constraint, "qfrc_constraint")
      _assert_eq(d.efc.force.numpy()[: mjd.nefc], mjd.efc_force, "efc_force")


if __name__ == "__main__":

  wp.init()
  absltest.main()
