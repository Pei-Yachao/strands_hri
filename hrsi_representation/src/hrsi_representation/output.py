# -*- coding: utf-8 -*-

import json
import numpy as np
from std_msgs.msg import Header
from hrsi_representation.msg import QTCArray, QTC

def write_files(qtc, filenames, path):
    for q,f in zip(qtc,filenames):
        write_file(q, path+'/'+f.replace('csv','qsr'))

def write_file(qtc, filename):
    with open(filename, 'w') as outfile:
        outfile.write(json.dumps(np.array(qtc[0]).tolist(), separators=(',', ':')).replace('],', '],\n'))

def create_qtc_array_msg(header=None, stamp=None, seq=None, frame_id=None, qtc=None):
    if not header:
        header = Header()
    out = QTCArray(qtc=qtc) # Assigning qtc as None by default due to function definitions and mutable objects in python
    out.header = header
    out.header.frame_id = frame_id if frame_id else header.frame_id
    out.header.stamp = stamp if stamp else header.stamp
    out.header.seq = seq if seq else header.seq
    return out

def create_qtc_msg(
        qtc_type, uuid, smoothing_rate,
        qtc_robot_human, prob_distance_robot_human, qtc_goal_human, prob_distance_goal_human,
        quantisation_factor=0.01, distance_threshold=1.2, abstract_distance_threshold='',
        collapsed=True, validated=True):
    qtc_msg = QTC(
        collapsed=collapsed, qtc_type=qtc_type,
        quantisation_factor=quantisation_factor,
        distance_threshold=distance_threshold,
        abstract_distance_threshold=abstract_distance_threshold,
        smoothing_rate=smoothing_rate, validated=validated, uuid=uuid,
        qtc_robot_human=qtc_robot_human,
        prob_distance_robot_human=prob_distance_robot_human,
        qtc_goal_human=qtc_goal_human,
        prob_distance_goal_human=prob_distance_goal_human
    )
    return qtc_msg