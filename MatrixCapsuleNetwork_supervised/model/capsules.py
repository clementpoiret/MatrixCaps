'''
Created on Jun 11, 2018

@author: jens
'''
# TODO: use less permute() and contiguous()

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import math
import model.util as util
import numpy as np

torch.manual_seed(1991)
torch.cuda.manual_seed(1991)


class PrimaryCaps(nn.Module):
    """
    Primary Capsule layer is nothing more than concatenate several convolutional
    layer together.
    Args:
        A:input channel
        B:number of types of capsules.

    """

    def __init__(self, A=32, B=32, h=4):
        super(PrimaryCaps, self).__init__()
        self.B = B
        
        self.capsules_pose = nn.Conv2d(in_channels=A, out_channels=B*h*h,
                            kernel_size=1, stride=1, bias=True)
        self.capsules_activation = nn.Conv2d(in_channels=A, out_channels=B,
                            kernel_size=1, stride=1, bias=True)

    def forward(self, x):  # b,14,14,32
        poses = self.capsules_pose(x)
        sh = poses.shape
        poses = poses.view(sh[0], -1, self.B, sh[2], sh[3]).permute(0, 2, 3, 4, 1).contiguous()
        activations = self.capsules_activation(x)
        activations = torch.sigmoid(activations)
        return poses, activations


class ConvCaps(nn.Module):
    """
    Convolutional Capsule Layer.
    Args:
        B:input number of types of capsules.
        C:output number of types of capsules.
        kernel: kernel of convolution. kernel=0 means the capsules in layer L+1's
        receptive field contain all capsules in layer L. Kernel=0 is used in the
        final ClassCaps layer.
        stride:stride of convolution
        iteration: number of EM iterations
        coordinate_add: whether to use Coordinate Addition
        transform_share: whether to share transformation matrix.

    """

    def __init__(self, B=32, C=32, kernel=3, stride=2, h=4, iteration=3,
                 coordinate_add=False, transform_share=False):
        super(ConvCaps, self).__init__()
        self.B = B
        self.C = C
        self.K = kernel  # kernel = 0 means full receptive field like class capsules
        self.Bkk = None
        self.Cww = None
        #self.b = args.batch_size
        self.stride = stride
        self.coordinate_add = coordinate_add
        self.transform_share = transform_share
        self.beta_v = nn.Parameter(torch.randn(self.C).view(1,self.C,1,1))
        self.beta_a = nn.Parameter(torch.randn(self.C).view(1,self.C,1))

        if transform_share:
            self.W = nn.Parameter(torch.randn(B, C, h, h))  # B,C,4,4
        else:
            self.W = nn.Parameter(torch.randn(B, kernel, kernel, C, h, h))  # B,K,K,C,4,4

        self.iteration = iteration

        self.h = h
        self.hh = self.h*self.h
        self.eps = 1e-10
        self.ln_2pi = torch.FloatTensor(1).fill_(math.log(2*math.pi))
        self.w = 1
        self.initial = True

    def _apply(self, fn):
        if fn.__qualname__.find('cuda') != -1:
            self.ln_2pi = self.ln_2pi.cuda()
        elif fn.__qualname__.find('cpu') != -1:
            self.ln_2pi = self.ln_2pi.cpu()
        super()._apply(fn)
        
    def create_coordinate_offset(self):
        dist = torch.arange(float(self.K)) / self.K
        off = torch.zeros(self.K, self.K, self.h, self.h)
        off[:,:,0,3] = dist
        off[:,:,1,3] = dist.view(3,1)
        if self.W.is_cuda:
            off = off.cuda()
        self.coord_offset = Variable(off).view(1, 1, self.K, self.K, 1, 1, 1, self.h, self.h)
        self.initial = False
        
        #votes[:, :, :, :, :, :, :, :2, -1] = votes[:, :, :, :, :, :, :, :2, -1] + add

    def EM_routing(self, lambda_, a_, V):
        # routing coefficient
        if self.W.is_cuda:
            R = Variable(torch.ones([self.b, self.Bkk, self.Cww]), requires_grad=False).cuda() / self.C
        else:
            R = Variable(torch.ones([self.b, self.Bkk, self.Cww]), requires_grad=False) / self.C

        for i in range(self.iteration):
            # M-step
            R = (R * a_).unsqueeze(-1)
            sum_R = R.sum(1)
            mu = ((R * V).sum(1) / sum_R).unsqueeze(1)
            V_minus_mu_sqr = (V - mu) ** 2
            self.sigma_square = ((R * V_minus_mu_sqr).sum(1) / sum_R).unsqueeze(1)

            """
            beta_v: Bias for log probability of sigma ("standard deviation")
            beta_a: Bias for offsetting
            
            In principle, beta_v and beta_a are only for learning regarding "activations".
            Just like "batch normalization" it has both scaling and bias.
            Votes are routed by the learned weight self.W.
            """
            log_sigma = torch.log(self.sigma_square.sqrt()+self.eps)
            cost = (self.beta_v + log_sigma.view(self.b,self.C,-1,self.hh)) * sum_R.view(self.b, self.C,-1,1)
            a = torch.sigmoid(lambda_ * (self.beta_a - cost.sum(-1)))
            a = a.view(self.b, self.Cww)

            # E-step
            if i != self.iteration - 1:
                ln_p_j_h = -V_minus_mu_sqr / (2 * self.sigma_square) - log_sigma - 0.5*self.ln_2pi
                p = torch.exp(ln_p_j_h)
                ap = a[:,None,:] * p.sum(-1)
                R = Variable(ap / (torch.sum(ap, 2, keepdim=True) + self.eps) + self.eps, requires_grad=False) # detaches from graph

        return a, mu

    #torch.save(poses, 'poses.pt')

    def forward(self, lambda_, poses, activations):
        self.width_in = int(poses.shape[2])
        if self.K:
            self.w = int((self.width_in - self.K) / self.stride) + 1
        self.Cww = self.w * self.w * self.C
        self.b = poses.size(0)
        if self.transform_share:
            if self.K == 0:
                self.K = self.width_in  # class Capsules' kernel = width_in
        self.Bkk = self.K * self.K * self.B
        
        if self.transform_share:
            W = self.W.view(self.B, 1, 1, self.C, self.h, self.h).expand(self.B, self.K, self.K, self.C, self.h, self.h).contiguous()
        else:
            W = self.W  # B,K,K,C,4,4

        # used to store every capsule i's poses in each capsule c's receptive field
        #pose = poses.contiguous()  # b,16*32,12,12
        #pose = poses.view(self.b, self.B, self.width_in, self.width_in, self.hh)

        pose_list = []
        for j in range(self.w):
            for i in range(self.w):
                pose_list.append( poses[:, :, self.stride * i:self.stride * i + self.K, self.stride * j:self.stride * j + self.K, :] )
        poses = torch.stack(pose_list, dim=-2)  # b,B,K,K,w*w,16
        
        poses = poses.view(self.b, self.B, self.K, self.K, 1, self.w, self.w, self.h, self.h)  # b,B,K,K,1,w,w,4,4
        W_hat = W[None, :, :, :, :, None, None, :, :]  # 1,B,K,K,C,1,1,4,4
        votes = W_hat @ poses  # b,B,K,K,C,w,w,4,4

        if self.coordinate_add:
            if (self.initial):
                self.create_coordinate_offset()
            votes = votes + self.coord_offset
            activations_ = activations.view(self.b, -1).unsqueeze(-1).repeat(1, 1, self.Cww)
        else:
            act_list = []
            for j in range(self.w):
                for i in range(self.w):
                    act_list.append( activations[:, :, self.stride * i:self.stride * i + self.K, self.stride * j:self.stride * j + self.K] )
            activations_ = torch.stack(act_list, dim=-1)  # b,B,K,K,w*w
            activations_ = activations_.view(self.b, self.Bkk, 1, -1).repeat(1, 1, self.C, 1).view(self.b, self.Bkk, self.Cww)

        votes = votes.view(self.b, self.Bkk, self.Cww, self.hh)
        activations, poses = self.EM_routing(lambda_, activations_, votes)
        
        return poses.view(self.b, self.C, self.w, self.w, -1), activations.view(self.b, self.C, self.w, self.w)


class ConvCapsDAE(nn.Module):
    def __init__(self, B, C, kernel, stride, hh):
        super(ConvCapsDAE, self).__init__()

        self.hh = hh
        self.h = int(hh ** 0.5)
        self.K = kernel
        self.B = B
        self.C = C
        self.stride = stride

        #self.transposed_conv2d = util.Conv2dGeneral(C, B, kernel, stride, hh, transposed=True)
        self.Wt = nn.Parameter(torch.randn(B, kernel, kernel, C, self.h, self.h))
        self.loss = nn.MSELoss(reduction='sum')

    def inverse_EM(self, mu, var, out_shape):
        mu_expanded = mu.expand(out_shape)
        sigma_expanded = var.sqrt().expand(out_shape)
        votes = torch.normal(mu_expanded, sigma_expanded)
        return votes

        """
        log_sigma = torch.log(self.sigma_square.sqrt()+self.eps)
        V_minus_mu_sqr = (votes - V) ** 2
        ln_p_j_h = -V_minus_mu_sqr / (2 * self.sigma_square) - log_sigma - 0.5*self.ln_2pi
        p = torch.exp(ln_p_j_h)
        ap = a[:,None,:] * p.sum(-1)
        R = ap / (torch.sum(ap, 2, keepdim=True) + self.eps) + self.eps
        R_orig = torch.ones([self.b, self.Bkk, self.Cww]) / self.C
        a_ = R / R_orig
        return a_, votes
        """
        
    def forward(self, poses, var, shp): # batch, channels, w, w, hh
        b = poses.shape[0]
        w = poses.shape[2]
        Bkk = self.B*self.K*self.K
        Cww = self.C*w*w
        poses = poses.view(b, 1, Cww, -1)
        votes_shape = torch.Size([b, Bkk, Cww, self.hh])
        votes_recon = self.inverse_EM(poses, var, votes_shape)
        votes_recon = votes_recon.view(b,self.B,self.K,self.K,self.C,w,w,self.h,self.h)

        W_hat = self.Wt[None, :, :, :, :, None, None, :, :]
        votes_recon = W_hat @ votes_recon
        
        votes_recon = votes_recon.view(b, self.B, self.K, self.K, self.C, -1, self.hh).sum(4)
        
        #recon_list = torch.unbind(votes_recon, dim=-2)
        recon_poses = torch.zeros(shp).cuda()
        k = 0
        for j in range(w):
            for i in range(w):
                recon_poses[:, :, self.stride * i:self.stride * i + self.K, self.stride * j:self.stride * j + self.K, :] += votes_recon[:,:,:,:,k,:] #recon_list[k]
                k += 1

        return recon_poses
        
        #poses_recon = votes_recon.view(b,Bkk,self.C,w,w,-1).sum(1)
        #poses_recon = self.transposed_conv2d(poses_recon)


class CapsNet(nn.Module):
    def __init__(self, args, A=32, AA=32, B=32, C=32, D=32, E=10, r=3, h=4):
        super(CapsNet, self).__init__()
        self.conv1 = nn.Conv2d(in_channels=4, out_channels=A, kernel_size=5, stride=2)
        self.bn1 = nn.BatchNorm2d(num_features=A, eps=0.001, momentum=0.1, affine=True)
        self.conv2 = nn.Conv2d(in_channels=A, out_channels=AA, kernel_size=5, stride=2, padding=1)
        self.bn2 = nn.BatchNorm2d(num_features=AA, eps=0.001, momentum=0.1, affine=True)
        """
        self.conv1 = nn.Conv2d(in_channels=4, out_channels=A, kernel_size=5, stride=2, padding=2)
        self.bn1 = nn.BatchNorm2d(num_features=A, eps=0.001, momentum=0.1, affine=True)
        self.conv2 = nn.Conv2d(in_channels=A, out_channels=AA, kernel_size=3, stride=2, padding=1)
        self.bn2 = nn.BatchNorm2d(num_features=AA, eps=0.001, momentum=0.1, affine=True)
        self.conv3 = nn.Conv2d(in_channels=AA, out_channels=AA, kernel_size=3, stride=2, padding=0)
        self.bn3 = nn.BatchNorm2d(num_features=AA, eps=0.001, momentum=0.1, affine=True)
        """
        self.primary_caps = PrimaryCaps(AA, B, h=h)
        self.convcaps1 = ConvCaps(B, C, kernel=3, stride=2, h=h, iteration=r, coordinate_add=False, transform_share=False)
        self.convcaps2 = ConvCaps(C, D, kernel=3, stride=1, h=h, iteration=r, coordinate_add=False, transform_share=False)
        self.classcaps = ConvCaps(D, E, kernel=0, stride=1, h=h, iteration=r, coordinate_add=True, transform_share=True)

        #if not args.disable_dae:
        """ Denoising Autoencoder """
        self.loss = nn.MSELoss(reduction='sum')
        self.Daeconv1 = nn.ConvTranspose2d(in_channels=A, out_channels=4, kernel_size=5, stride=2, output_padding=1)
        self.Daeconv2 = nn.ConvTranspose2d(in_channels=AA, out_channels=A, kernel_size=5, stride=2, padding=1, output_padding=1)
        self.DaePrim_pose = nn.ConvTranspose2d(in_channels=B*h*h, out_channels=AA, kernel_size=1, stride=1, bias=True)
        self.DaePrim_activation = nn.ConvTranspose2d(in_channels=B, out_channels=AA, kernel_size=1, stride=1, bias=True)
        self.DaeCaps1 = ConvCapsDAE(B, C, kernel=3, stride=2, hh=h*h)
        self.DaeCaps2 = ConvCapsDAE(C, D, kernel=3, stride=1, hh=h*h)
        
        self.coord_add_encoder = nn.Sequential(
            nn.Linear(3, 128),
            nn.ReLU(inplace=True),
            nn.Linear(128, 3),
            nn.Tanh()
        )
        """
        self.coord_add_encoder = nn.Sequential(
            nn.Linear(3, 128),
            nn.ReLU(inplace=True),
            nn.Linear(128, 3),
            nn.Tanh()
        )
        """

        lin1 = nn.Linear(h*h * args.num_classes, 512)
        #lin1 = nn.Linear(3*4 * args.num_classes, 512)
        lin1.weight.data *= 50.0 # inialize weights strongest here!
        lin2 = nn.Linear(512, 4096)
        lin2.weight.data *= 0.1
        lin3 = nn.Linear(4096, 20000)
        lin3.weight.data *= 0.1

        
        self.decoder = nn.Sequential(
            #nn.Linear(h*h * args.num_classes, 1024),   # 16 - 1024 - 10240 - 10000
            lin1,
            nn.ReLU(inplace=True),
            #nn.Linear(1024, 10240),
            lin2,
            nn.ReLU(inplace=True),
            #nn.Linear(10240, 10000),
            lin3,
            nn.Sigmoid()
        )
        self.num_classes = E

        self.args = args

    def forward(self, lambda_, x, labels=None):
        dae_loss = 0
        if not self.args.disable_encoder:
            
            """ convolution 1 and DAE"""
            x1 = x #* (x.data.new(x.size()).normal_(0, 0.1) > -.1).type_as(x)
            #x1 = x + torch.cuda.FloatTensor( np.random.normal(loc=0.0, scale=0.1, size=x.shape) )
            x1 = self.conv1(x1)
            x1 = self.bn1(x1)
            x1 = F.relu(x1)
            if not self.args.disable_dae:
                x2 = self.Daeconv1(x1)
                x2 = F.relu(x2)
                dae_loss = self.loss(x2, x)
            
            x = F.max_pool2d(x1,2, 2)

            """ convolution 2 and DAE"""
            x1 = x #* (x.data.new(x.size()).normal_(0, 0.1) > -.1).type_as(x)
            #x1 = x + torch.cuda.FloatTensor( np.random.normal(loc=0.0, scale=0.1, size=x.shape) )
            x1 = self.conv2(x1)
            x1 = self.bn2(x1)
            x1 = F.relu(x1)
            if not self.args.disable_dae:
                x2 = self.Daeconv2(x1)
                x2 = F.relu(x2)
                dae_loss += self.loss(x2, x)

            """ Primary Capsules """
            x = x1
            x1 = x #* (x.data.new(x.size()).normal_(0, 0.1) > -.1).type_as(x)
            #x1 = x + torch.cuda.FloatTensor( np.random.normal(loc=0.0, scale=0.1, size=x.shape) )
            p, a = self.primary_caps(x1)

            """ DAE Primary Capsules """
            #        logit_a = torch.log(a / (1-a))
            if not self.args.disable_dae:
                dae_a = self.DaePrim_activation(a)
                dae_a = F.relu(dae_a)
                dae_loss += self.loss(dae_a, x)
                shp = p.shape
                dae_pose = p.permute(0,4,1,2,3).contiguous().view(shp[0],shp[4]*shp[1],shp[2],shp[3])
                dae_pose = self.DaePrim_pose(dae_pose)
                dae_pose = F.relu(dae_pose)
                dae_loss += self.loss(dae_pose, x)


            """ convcaps1 """
            #p1 = p * (p.data.new(p.size()).normal_(0, 0.1) > -.1).type_as(p)
            p1 = p #+ torch.cuda.FloatTensor( np.random.normal(loc=0.0, scale=0.1, size=p.shape) )
            p1, a = self.convcaps1(lambda_, p1, a)

            """ DAE1 """
            if not self.args.disable_dae:
                recon_poses = self.DaeCaps1(p1, self.convcaps1.sigma_square, p.shape)
                dae_loss += self.loss(recon_poses, p)

            
            """ convcaps2 """
            #p = p1 * (p1.data.new(p1.size()).normal_(0, 0.1) > -.1).type_as(p1)
            p = p1 #+ torch.cuda.FloatTensor( np.random.normal(loc=0.0, scale=0.1, size=p1.shape) )
            p, a = self.convcaps2(lambda_, p, a)

            """ DAE2 """
            if not self.args.disable_dae:
                recon_poses = self.DaeCaps2(p, self.convcaps2.sigma_square, p1.shape)
                dae_loss += self.loss(recon_poses, p1)

            """ classcaps """
            p, a = self.classcaps(lambda_, p, a)


            p = p.squeeze()
            
            # Temporary when batch size = 1
            if len(p.shape) == 1:
                p = p.unsqueeze(0)
                
            xyz = p[:, (3,7,11)]
            xyz = self.coord_add_encoder(xyz)
            p[:, (3,7,11)] = xyz * 1.0
        else:
            p = labels

        # convert to one hot
        #y = Variable(torch.eye(self.num_classes)).cuda().index_select(dim=0, index=y)
        if not self.args.disable_recon:
            reconstructions = self.decoder(p)
            #if labels is None:
            #    reconstructions = self.decoder(p)
            #else:
            #    labels44 = qmat(p).view(p.shape[0],-1)
            #    reconstructions = self.decoder(labels44)
        else:
            reconstructions = torch.zeros(1)

        return p, reconstructions, dae_loss


class CapsuleLoss(nn.Module):
    def __init__(self, args):
        super(CapsuleLoss, self).__init__()
        self.reconstruction_loss = nn.MSELoss(reduction='sum')
        self.loss = nn.MSELoss(reduction='sum') #args.loss
        self.args = args

    @staticmethod
    def spread_loss(x, target, m):  # x:b,10 target:b
        loss = F.multi_margin_loss(x, target, p=2, margin=m)
        return loss

    @staticmethod
    def cross_entropy_loss(x, target, m):
        loss = F.cross_entropy(x, target)
        return loss

    @staticmethod
    def margin_loss(x, labels, m):
        left = F.relu(0.9 - x, inplace=True) ** 2
        right = F.relu(x - 0.1, inplace=True) ** 2

        labels = Variable(torch.eye(args.num_classes).cuda()).index_select(dim=0, index=labels)

        margin_loss = labels * left + 0.5 * (1. - labels) * right
        margin_loss = margin_loss.sum()
        return margin_loss * 1/x.size(0)

    def forward(self, images, output=None, labels=None, recon=None):
        #main_loss = getattr(self, self.loss)(output, labels, m)
        if self.args.disable_encoder or labels is None:
            main_loss = 0
        else:
            main_loss = self.loss(output, labels)

        if not self.args.disable_recon:
            recon_loss = self.reconstruction_loss(recon, images)
            main_loss += self.args.recon_factor * recon_loss

        return main_loss
