from multiprocessing import Value

import numpy as np
import torch
from yarr.agents.agent import Agent
from yarr.envs.env import Env
from yarr.utils.transition import ReplayTransition
from typing import List


class RolloutGenerator(object):

    def _get_type(self, x):
        if x.dtype == np.float64:
            return np.float32
        return x.dtype

    def generator(self, step_signal: Value, env: Env, agent: Agent,
                  episode_length: int, timesteps: int,
                  eval: bool, eval_demo_seed: int = 0,
                  record_enabled: bool = False, act_gt_keypoint_demos: List[List[np.array]] = None):

        if eval:
            obs = env.reset_to_demo(eval_demo_seed)
        else:
            obs = env.reset()

        agent.reset()
        obs_history = {k: [np.array(v, dtype=self._get_type(v))] * timesteps for k, v in obs.items()}
        for step in range(episode_length):
            
            if act_gt_keypoint_demos is None:
                #prepped_data = {k:torch.tensor([v], device=self._env_device) for k, v in obs_history.items()}
                prepped_data = {k:torch.tensor(np.array([v]), device=self._env_device) for k, v in obs_history.items()}
                act_result = agent.act(step_signal.value, prepped_data,
                                    deterministic=eval)
                # # warmup
                # import time
                # for _ in range(100):
                #     with torch.no_grad():
                #         act_result = agent.act(step_signal.value, prepped_data,
                #                     deterministic=eval)

                
                # num_iterations = 1000
                # start_time = time.time()
                # with torch.no_grad():
                #     for _ in range(num_iterations):
                #         act_result = agent.act(step_signal.value, prepped_data,
                #                     deterministic=eval)
                # end_time = time.time()
                # total_time = end_time - start_time

                # # FPS
                # fps = num_iterations / total_time
                # print(f'total_time: {total_time}')
                # print(f'FPS: {fps:.6f}')
                # exit()
                
            elif len(act_gt_keypoint_demos[eval_demo_seed]) <= step:
                print('The step number is larger than keypoint number')
                prepped_data = {k:torch.tensor(np.array([v]), device=self._env_device) for k, v in obs_history.items()}
                act_result = agent.act(step_signal.value, prepped_data,
                                    deterministic=eval)
            else:
                act_result = act_gt_keypoint_demos[eval_demo_seed][step]

            # Convert to np if not already
            agent_obs_elems = {k: np.array(v) for k, v in
                               act_result.observation_elements.items()}
            extra_replay_elements = {k: np.array(v) for k, v in
                                     act_result.replay_elements.items()}

            transition = env.step(act_result)
            obs_tp1 = dict(transition.observation)
            timeout = False
            if step == episode_length - 1:
                # If last transition, and not terminal, then we timed out
                timeout = not transition.terminal
                if timeout:
                    transition.terminal = True
                    if "needs_reset" in transition.info:
                        transition.info["needs_reset"] = True

            obs_and_replay_elems = {}
            obs_and_replay_elems.update(obs)
            obs_and_replay_elems.update(agent_obs_elems)
            obs_and_replay_elems.update(extra_replay_elements)

            for k in obs_history.keys():
                obs_history[k].append(transition.observation[k])
                obs_history[k].pop(0)

            transition.info["active_task_id"] = env.active_task_id

            replay_transition = ReplayTransition(
                obs_and_replay_elems, act_result.action, transition.reward,
                transition.terminal, timeout, summaries=transition.summaries,
                info=transition.info)

            if transition.terminal or timeout:
                # If the agent gives us observations then we need to call act
                # one last time (i.e. acting in the terminal state).
                if len(act_result.observation_elements) > 0:
                    #prepped_data = {k: torch.tensor([v], device=self._env_device) for k, v in obs_history.items()}
                    prepped_data = {k:torch.tensor(np.array([v]), device=self._env_device) for k, v in obs_history.items()}
                    act_result = agent.act(step_signal.value, prepped_data,
                                           deterministic=eval)
                    agent_obs_elems_tp1 = {k: np.array(v) for k, v in
                                           act_result.observation_elements.items()}
                    obs_tp1.update(agent_obs_elems_tp1)
                replay_transition.final_observation = obs_tp1

            if record_enabled and (transition.terminal or timeout or step == episode_length - 1):
                env.env._action_mode.arm_action_mode.record_end(env.env._scene,
                                                                steps=60, step_scene=True)

            obs = dict(transition.observation)
            yield replay_transition

            if transition.info.get("needs_reset", transition.terminal):
                return
