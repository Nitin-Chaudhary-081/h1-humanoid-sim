"""ONNX export of PureNumPyPolicy — hand-built graph via onnx.helper.

Graph: obs[1,OBS] -> Gemm -> Tanh -> Gemm -> Tanh -> Mul(scale) -> act[1,ACT]
Opset 13, float32 initializers.
"""

import numpy as np

OPSET = 13


def build_graph(policy):
    import onnx
    from onnx import TensorProto, helper

    scale = helper.make_tensor('act_scale', TensorProto.FLOAT, [1],
                               [float(policy.act_scale)])
    nodes = [
        helper.make_node('Gemm', ['obs', 'W1', 'b1'], ['h_pre'],
                         transB=0),
        helper.make_node('Tanh', ['h_pre'], ['h']),
        helper.make_node('Gemm', ['h', 'W2', 'b2'], ['a_pre']),
        helper.make_node('Tanh', ['a_pre'], ['a']),
        helper.make_node('Mul', ['a', 'act_scale'], ['act']),
    ]
    inputs = [helper.make_tensor_value_info(
        'obs', TensorProto.FLOAT, [None, policy.obs_dim])]
    outputs = [helper.make_tensor_value_info(
        'act', TensorProto.FLOAT, [None, policy.act_dim])]
    inits = [
        onnx.numpy_helper.from_array(
            policy.W1.astype(np.float32), 'W1'),
        onnx.numpy_helper.from_array(
            policy.b1.astype(np.float32), 'b1'),
        onnx.numpy_helper.from_array(
            policy.W2.astype(np.float32), 'W2'),
        onnx.numpy_helper.from_array(
            policy.b2.astype(np.float32), 'b2'),
        scale,
    ]
    graph = helper.make_graph(nodes, 'h1_rl_policy', inputs, outputs,
                              initializer=inits)
    model = helper.make_model(graph, opset_imports=[
        helper.make_opsetid('', OPSET)])
    model.ir_version = 8  # broad runtime compatibility
    return model


def export_onnx(policy, path):
    import onnx
    model = build_graph(policy)
    onnx.checker.check_model(model)
    onnx.save(model, path)
    return path


def onnx_forward(path, obs):
    """Run the exported model with the onnx reference evaluator."""
    import onnx
    from onnx.reference import ReferenceEvaluator
    sess = ReferenceEvaluator(onnx.load(path))
    batched = np.asarray(obs, dtype=np.float32)
    if batched.ndim == 1:
        batched = batched[None, :]
        return sess.run(['act'], {'obs': batched})[0][0]
    return sess.run(['act'], {'obs': batched})[0]


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog='rl_export',
                                description='Export trained policy to ONNX')
    p.add_argument('--params', required=True,
                   help='.npy file of flat params from rl_train --save')
    p.add_argument('--obs-dim', type=int, default=12)
    p.add_argument('--act-dim', type=int, default=4)
    p.add_argument('--hidden-dim', type=int, default=16)
    p.add_argument('--out', required=True, help='output .onnx path')
    args = p.parse_args(argv)

    from .policy import PureNumPyPolicy
    policy = PureNumPyPolicy(args.obs_dim, args.act_dim,
                             hidden_dim=args.hidden_dim)
    policy.set_params(np.load(args.params))
    export_onnx(policy, args.out)
    print('exported %s' % args.out)
    return 0
