"""A constant-velocity Kalman filter over a 3D ENU position, used to smooth and predict each drone."""
import numpy as np

_I3 = np.eye(3)


def _transition(dt, accel_noise):
    f = np.eye(6)
    f[:3, 3:] = _I3 * dt
    # Discrete white-noise acceleration model: unknown accelerations of std accel_noise (m/s^2)
    q = accel_noise ** 2 * np.block([[dt ** 4 / 4 * _I3, dt ** 3 / 2 * _I3],
                                     [dt ** 3 / 2 * _I3, dt ** 2 * _I3]])
    return f, q


class ConstantVelocityFilter:
    """State is [e, n, u, ve, vn, vu] in metres and m/s, timestamped in epoch seconds."""

    def __init__(self, t, pos, vel=None, *, accel_noise, pos_sigma, vel_sigma, initial_vel_sigma=15.0):
        self.accel_noise = accel_noise
        self.pos_sigma = pos_sigma
        self.vel_sigma = vel_sigma
        self.t = t
        self.x = np.zeros(6)
        self.x[:3] = pos
        if vel is not None:
            self.x[3:] = vel
        v_var = vel_sigma ** 2 if vel is not None else initial_vel_sigma ** 2
        self.p = np.diag([pos_sigma ** 2] * 3 + [v_var] * 3)

    @property
    def position(self):
        return self.x[:3].copy()

    @property
    def velocity(self):
        return self.x[3:].copy()

    def state_at(self, t):
        """
        Predict the state at time t without changing the filter.
        :return: (position, velocity, 6x6 covariance)
        """
        dt = t - self.t
        if dt <= 0:
            return self.x[:3].copy(), self.x[3:].copy(), self.p.copy()
        f, q = _transition(dt, self.accel_noise)
        x = f @ self.x
        return x[:3], x[3:], f @ self.p @ f.T + q

    def predict(self, t):
        if t > self.t:
            pos, vel, self.p = self.state_at(t)
            self.x = np.concatenate([pos, vel])
            self.t = t

    def update(self, t, pos, vel=None):
        self.predict(t)
        if vel is None:
            h = np.hstack([_I3, np.zeros((3, 3))])
            z = np.asarray(pos, dtype=float)
            r = _I3 * self.pos_sigma ** 2
        else:
            h = np.eye(6)
            z = np.concatenate([pos, vel]).astype(float)
            r = np.diag([self.pos_sigma ** 2] * 3 + [self.vel_sigma ** 2] * 3)
        innovation = z - h @ self.x
        s = h @ self.p @ h.T + r
        k = self.p @ h.T @ np.linalg.inv(s)
        self.x = self.x + k @ innovation
        i_kh = np.eye(6) - k @ h
        self.p = i_kh @ self.p @ i_kh.T + k @ r @ k.T  # Joseph form keeps P symmetric positive-definite
