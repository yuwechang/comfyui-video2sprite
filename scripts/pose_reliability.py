"""Shared evidence checks and confidence-aware distances for pose research only."""
import numpy as np

JOINTS=(11,12,13,14,15,16,23,24,25,26,27,28,29,30,31,32)
POLICY='visible-joints-masked-appearance-v2'


def input_quality(positions,visibility,start,end,appearance=None):
    positions=np.asarray(positions);visibility=np.asarray(visibility)
    if positions.shape!=(end-start+1,len(JOINTS),2) or visibility.shape!=positions.shape[:2]:
        return {'passed':False,'reason':'incomplete_pose_sequence'}
    if not np.isfinite(positions).all() or not np.isfinite(visibility).all():
        return {'passed':False,'reason':'nonfinite_pose_sequence'}
    if np.any((visibility<0)|(visibility>1)):
        return {'passed':False,'reason':'invalid_visibility'}
    affected=[{'frame':start+i,'joints':[JOINTS[j] for j in np.flatnonzero(row<.5)],
               'min_visibility':float(row.min())} for i,row in enumerate(visibility) if (row<.5).any()]
    if appearance is not None:
        appearance=np.asarray(appearance)
        if len(appearance)!=len(positions) or not np.isfinite(appearance).all():
            return {'passed':False,'reason':'invalid_appearance_sequence'}
    # Missing joints describe missing observations, never a motionless limb.
    # Image evidence is required to supplement any unobserved component.
    reason='appearance_required_for_occlusion' if affected and appearance is None else None
    return {'passed':reason is None,'reason':reason,
            'policy':POLICY,'visibility_threshold':.5,'affected_frames':affected,
            'appearance_available':appearance is not None,'manual_substitution':False}


def confidence_weights(visibility):
    # Exclude unavailable coordinates rather than trusting a model's hidden pose.
    return (np.asarray(visibility,float)>=.5).astype(float)


def weighted_smooth(positions,weights,radius=1):
    positions=np.asarray(positions,float);rows=[]
    for i in range(len(positions)):
        a=max(0,i-radius);b=min(len(positions),i+radius+1);w=weights[a:b]
        denominator=w.sum(axis=0)
        rows.append(np.divide((positions[a:b]*w[...,None]).sum(axis=0),denominator[:,None],
                             out=positions[i].copy(),where=denominator[:,None]>0))
    return np.asarray(rows)


def distance(a,b,weights,allow_missing=False):
    lengths=np.linalg.norm(a-b,axis=-1);weights=np.asarray(weights,float)
    denominator=weights.sum(axis=-1)
    if not allow_missing and np.any(denominator<=0):raise ValueError('No shared reliable pose evidence')
    return np.divide((lengths*weights).sum(axis=-1),denominator,
                     out=np.zeros_like(denominator),where=denominator>0)


class EvidenceMetric:
    """Pose error plus image evidence for unavailable joints; no action labels."""
    def __init__(self,poses,weights,appearance=None):
        self.poses=np.asarray(poses);self.weights=np.asarray(weights)
        self.appearance=None if appearance is None else np.asarray(appearance).reshape(len(poses),-1)
        if np.any(self.weights<1) and self.appearance is None:
            raise ValueError('Masked appearance evidence required for occlusion')
        self.pose_scale=max(float(np.max(distance(self.poses,self.poses[0],
            np.minimum(self.weights,self.weights[0]),allow_missing=True))),1e-12)
        if self.pose_scale<=1e-12:self.pose_scale=1.0
        self.image_scale=(max(float(np.max(np.sqrt(np.mean(
            (self.appearance-self.appearance[0])**2,axis=-1)))),1e-12)
            if self.appearance is not None else 1.0)

    def interpolation(self,a,b,indices,fractions):
        indices=np.asarray(indices);fractions=np.asarray(fractions)
        prediction=self.poses[a]+fractions[...,None,None]*(self.poses[b]-self.poses[a])
        common=np.minimum(self.weights[indices],np.minimum(self.weights[a],self.weights[b]))
        error=distance(self.poses[indices],prediction,common,allow_missing=True)
        missing=1-common.mean(axis=-1)
        if self.appearance is not None:
            prediction_image=self.appearance[a]+fractions[...,None]*(self.appearance[b]-self.appearance[a])
            image_error=np.sqrt(np.mean((self.appearance[indices]-prediction_image)**2,axis=-1))
            error=np.maximum(error,missing*image_error/self.image_scale*self.pose_scale)
        elif np.any(missing>0):raise ValueError('No complete shared evidence')
        return error

    def pairs(self):
        return np.asarray([self.interpolation(i,i,np.arange(len(self.poses)),
            np.zeros(len(self.poses))) for i in range(len(self.poses))])
