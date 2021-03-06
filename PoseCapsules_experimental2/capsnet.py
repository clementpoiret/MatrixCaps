'''
Created on Jan 14, 2019

@author: jens
'''
import torch
import torch.nn as nn
from collections import OrderedDict
import layers
import layers2
import batchrenorm as af

class MSELossWeighted(nn.Module):
    def __init__(self, batch_size=1, transition_loss=0., weight=None, weight2=None, pretrained=False):
        super(MSELossWeighted, self).__init__()
        if weight is None:
            weight = torch.tensor([1.,1.,1.,1.,1.,1.,1.,1.,1.,1.]).cuda()
            weight = 10. * weight / weight.sum()
        if weight2 is None:
            weight2 = torch.tensor([1.,1.,1.,1.,1.,1.,5.,5.,5.,1.]).cuda()
        
        self.weight = weight
        self.transition_loss = transition_loss
        self.batch_size = batch_size
        self.weight2 = weight2
        self.pretrained = pretrained
        self.trans = (weight2 - weight) / 300.
        self.count = -1
        
        
    def forward(self, input, target):
        pct_var = input-target
        out = (pct_var * self.weight.expand_as(target)) ** 2
        loss = out.sum() 
        if self.count < 300:
            if self.count > -1:
                self.count += 1
                self.weight = self.weight + self.trans
            else:
                if loss/self.batch_size < self.transition_loss:
                    self.count = 0
                    if self.pretrained:
                        self.weight = self.weight2
                        self.count = 300
        return loss        


def insert(ordereddict, key, newkey, object):
    new_orderded_dict=ordereddict.__class__()
    for i, value in ordereddict.items():
        new_orderded_dict[i]=value
        if i==key:
            new_orderded_dict[newkey]=object
    ordereddict.clear()
    ordereddict.update(new_orderded_dict)


class CapsNet(nn.Module):
    def __init__(self, args, len_dataset, stat=None):
        super(CapsNet, self).__init__()

        self.recon_factor = nn.Parameter(torch.tensor(0.), requires_grad=False)
        self.regularize_factor = nn.Parameter(torch.tensor(1e-6), requires_grad=False)
        self.routing_list = []

        if args.dataset == 'rabbit200x100':
            """
            OBS: primary caps 2 and 3 should be WITHOUT BIAS!! Bias is NOT good...!
            """
            layer_list = OrderedDict()
            right_container = []
            layer_list['split_stereo'] = layers2.SplitStereoReturnLeftLayer(right_container)
            
            layer_list['posenc'] = layers.PosEncoderLayer()
            layer_list['conv1'] = nn.Conv2d(in_channels=3+1, out_channels=10, kernel_size=15, stride=1, padding=7, bias=False)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            #nn.init.normal_(layer_list['conv1'].bias.data, mean=0,std=0.1)
            layer_list['bn1'] = nn.BatchNorm2d(num_features=10, eps=0.001, momentum=0.1, affine=True)
            layer_list['relu1'] = nn.ReLU(inplace=True)

            layer_list['prim1'] = layers.PrimMatrix2d(output_dim=8, h=9, kernel_size=15, stride=2, padding=7, bias=True)
            layer_list['bnn1'] = layers2.BNLayer()
            layer_list['route1'] = layers.MatrixRouting(output_dim=8, num_routing=1)

            layer_list['prim2'] = layers.PrimMatrix2d(output_dim=8, h=9, kernel_size=9, stride=2, padding=4, bias=False, advanced=True)
            layer_list['bnn2'] = layers2.BNLayer()
            layer_list['route2'] = layers.MatrixRouting(output_dim=8, num_routing=3)

            layer_list['prim3'] = layers.PrimMatrix2d(output_dim=32, h=14, kernel_size=9, stride=2, padding=4, bias=False, advanced=True)
            layer_list['bnn3'] = layers2.BNLayer()
            layer_list['route3'] = layers.MatrixRouting(output_dim=32, num_routing=3)


            left_container = []
            layer_list['store_left'] = layers2.StoreLayer(left_container, False)
            layer_list['activate_right'] = layers2.ActivatePathway(right_container)
            layer_list['right_posenc'] = layer_list['posenc']
            layer_list['right_conv1'] = layer_list['conv1']
            layer_list['right_bn1'] = layer_list['bn1']
            layer_list['right_relu1'] = layer_list['relu1']
            layer_list['right_prim1'] = layer_list['prim1']
            layer_list['right_bnn1'] = layer_list['bnn1']
            layer_list['right_route1'] = layer_list['route1']
            layer_list['right_prim2'] = layer_list['prim2']
            layer_list['right_bnn2'] = layer_list['bnn2']
            layer_list['right_route2'] = layer_list['route2'] 
            layer_list['right_prim3'] = layer_list['prim3']
            layer_list['right_bnn3'] = layer_list['bnn3']
            layer_list['right_route3'] = layer_list['route3']
            layer_list['concat'] = layers2.ConcatLayer(left_container, do_clone=False)


            self.decoder_input_atoms = 10
            layer_list['prim4'] = layers.PrimMatrix2d(output_dim=1, h=self.decoder_input_atoms, kernel_size=0, stride=1, padding=0, bias=False, advanced=True)
            layer_list['bnn4'] = layers2.BNLayer()
            layer_list['route4'] = layers.MatrixRouting(output_dim=1, num_routing=3)
            self.capsules = nn.Sequential(layer_list)
            self.image_decoder = None

        elif args.dataset == 'rabbit100x100':
            """
            OBS: primary caps 2 and 3 should be WITHOUT BIAS!! Bias is NOT good...!
            """

            layer_list = OrderedDict()
            layer_list['posenc'] = layers.PosEncoderLayer()
            layer_list['conv1'] = nn.Conv2d(in_channels=3+1, out_channels=17, kernel_size=15, stride=1, padding=7, bias=False)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            layer_list['bn1'] = nn.BatchNorm2d(num_features=17, eps=0.001, momentum=0.1, affine=True)
            layer_list['relu1'] = nn.ReLU(inplace=True)

            layer_list['prim1'] = layers.PrimMatrix2d(output_dim=8, h=16, kernel_size=15, stride=2, padding=7, bias=True)
            layer_list['bnn1'] = layers2.BNLayer()
            layer_list['route1'] = layers.MatrixRouting(output_dim=8, num_routing=1)

            layer_list['prim2'] = layers.PrimMatrix2d(output_dim=8, h=16, kernel_size=9, stride=2, padding=4, bias=False, advanced=True)
            layer_list['bnn2'] = layers2.BNLayer()
            layer_list['route2'] = layers.MatrixRouting(output_dim=8, num_routing=3)

            layer_list['prim3'] = layers.PrimMatrix2d(output_dim=32, h=16, kernel_size=9, stride=2, padding=4, bias=False, advanced=True)
            layer_list['bnn3'] = layers2.BNLayer()
            layer_list['route3'] = layers.MatrixRouting(output_dim=32, num_routing=3)

            self.decoder_input_atoms = 10
            layer_list['prim4'] = layers.PrimMatrix2d(output_dim=1, h=self.decoder_input_atoms, kernel_size=0, stride=1, padding=0, bias=False, advanced=True)
            layer_list['bnn4'] = layers2.BNLayer()
            layer_list['route4'] = layers.MatrixRouting(output_dim=1, num_routing=3)
            self.capsules = nn.Sequential(layer_list)

            decoder_list = OrderedDict()
            #decoder_list['prepare'] = layers2.Pose2VectorRepLayer()
            decoder_list['1transposed'] = layers.PrimMatrix2d(output_dim=16, h=16, kernel_size=9, stride=1, padding=0, bias=False, advanced=True, func='ConvTranspose2d')
            decoder_list['bnn1_transposed'] = layers2.BNLayer()
            decoder_list['route1_transposed'] = layers.MatrixRouting(output_dim=16, num_routing=3)

            decoder_list['2transposed'] = layers.PrimMatrix2d(output_dim=16, h=16, kernel_size=9, stride=2, padding=0, bias=False, advanced=True, func='ConvTranspose2d')
            decoder_list['bnn2_transposed'] = layers2.BNLayer()
            decoder_list['route2_transposed'] = layers.MatrixRouting(output_dim=16, num_routing=3)

            decoder_list['3transposed'] = layers.PrimMatrix2d(output_dim=8, h=16, kernel_size=9, stride=2, padding=0, bias=False, advanced=True, func='ConvTranspose2d')
            decoder_list['bnn3_transposed'] = layers2.BNLayer()
            decoder_list['route3_transposed'] = layers.MatrixRouting(output_dim=8, num_routing=3)

            decoder_list['transform'] = layers.MatrixToConv()

            decoder_list['conv1_transposed'] = nn.ConvTranspose2d(in_channels=8*17, out_channels=3, kernel_size=7, stride=2, padding=10, output_padding=1, bias=True)
            nn.init.normal_(decoder_list['conv1_transposed'].weight.data, mean=0,std=0.1)

            self.image_decoder = nn.Sequential(decoder_list)

        elif args.dataset == 'MNIST':

            A, B, C, D, E, h = 32, 32, 32, 32, 10, 16
            img_size = 784
            
            layer_list = OrderedDict()
            layer_list['posenc'] = layers.PosEncoderLayer()
            layer_list['conv1'] = nn.Conv2d(in_channels=2, out_channels=A, kernel_size=5, stride=2, padding=0, bias=False)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            #nn.init.normal_(layer_list['conv1'].bias.data, mean=0,std=0.1)
            layer_list['bn1'] = nn.BatchNorm2d(num_features=A, eps=0.001, momentum=0.1, affine=True)
            layer_list['relu1'] = nn.ReLU(inplace=True)
    
            layer_list['prim1'] = layers.PrimMatrix2d(output_dim=B, h=16, kernel_size=1, stride=1, padding=0, bias=True, advanced=False)
            layer_list['bnn1'] = layers2.BNLayer()
            layer_list['route1'] = layers.MatrixRouting(output_dim=B, num_routing=1, experimental=False, sparse=None)
    
            layer_list['prim2'] = layers.PrimMatrix2d(output_dim=C, h=16, kernel_size=3, stride=2, padding=0, bias=False, advanced=True)
            layer_list['bnn2'] = layers2.BNLayer()
            layer_list['route2'] = layers.MatrixRouting(output_dim=C, num_routing=3, experimental=False) #, sparse=layers.SparseCoding(C, return_mask=True))
            #layer_list['boost2'] = layers.Boost()
    
            layer_list['prim2a'] = layers.PrimMatrix2d(output_dim=D, h=16, kernel_size=3, stride=1, padding=0, bias=False, advanced=True)
            layer_list['bnn2a'] = layers2.BNLayer()
            layer_list['route2a'] = layers.MatrixRouting(output_dim=D, num_routing=3, experimental=False) #, sparse=layers.SparseCoding(D, return_mask=True))
            #layer_list['boost2a'] = layers.Boost()
    
            layer_list['prim3'] = layers.PrimMatrix2d(output_dim=E, h=16, kernel_size=0, stride=1, padding=0, bias=False, advanced=True)
            layer_list['bnn3'] = layers2.BNLayer()
            #layer_list['route3'] = layers.MatrixRouting(output_dim=E, num_routing=3, experimental=False)
            route3 = layers.MatrixRouting(output_dim=E, num_routing=3, experimental=True, sparse=layers.SparseCoding(E, return_mask=False), stat=stat)
            self.routing_list.append(route3)
            layer_list['route3'] = route3
            #layer_list['boost3'] = layers.Boost()
            layer_list['cat'] = layers2.CatLayer()

            self.capsules = nn.Sequential(layer_list)

            self.image_decoder = nn.Sequential(
                layers2.MaskLayer(-1, one_hot=False),
                nn.Linear((h+1) * E, 512),
                nn.ReLU(inplace=True),
                nn.Linear(512, 1024),
                nn.ReLU(inplace=True),
                nn.Linear(1024, img_size),
                nn.Sigmoid()
            )

        elif args.dataset == 'MNIST_ORIGINAL':

            A, B, C, D, E, h = 32, 32, 32, 32, 10, 4
            
            layer_list = OrderedDict()
            layer_list['conv1'] = nn.Conv2d(in_channels=1, out_channels=A, kernel_size=5, stride=2, padding=0, bias=True)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            layer_list['relu1'] = nn.ReLU(inplace=True)
    
            layer_list['prim1'] = layers.PrimMatrix2d(output_dim=B, h=16, kernel_size=1, stride=1, padding=0, bias=True, advanced=False)
            layer_list['sigmoid1'] = layers2.SigmoidLayer()
            layer_list['route1'] = layers.MatrixRouting(output_dim=B, num_routing=1)
    
    
            layer_list['caps2'] = layers.ConvMatrix2d(output_dim=C, hh=16, kernel_size=3, stride=2)
            layer_list['route2'] = layers.MatrixRouting(output_dim=C, num_routing=3)

            layer_list['caps3'] = layers.ConvMatrix2d(output_dim=D, hh=16, kernel_size=3, stride=1)
            layer_list['route3'] = layers.MatrixRouting(output_dim=C, num_routing=3)

            layer_list['caps4'] = layers.ConvMatrix2d(output_dim=E, hh=16, kernel_size=0, stride=1)
            layer_list['route4'] = layers.MatrixRouting(output_dim=E, num_routing=3)

            self.capsules = nn.Sequential(layer_list)

            self.image_decoder = nn.Sequential(
                layers2.MaskLayer(E),
                nn.Linear(h*h * E, 512),
                nn.ReLU(inplace=True),
                nn.Linear(512, 1024),
                nn.ReLU(inplace=True),
                nn.Linear(1024, 784),
                nn.Sigmoid()
            )
            
        elif args.dataset == 'smallNORB':

            A, B, C, D, E, h = 17, 16, 32, 32, 5, 16
            img_size = 32*32

            layer_list = OrderedDict()
            layer_list['posenc'] = layers.PosEncoderLayer()
            layer_list['conv1'] = nn.Conv2d(in_channels=1+1, out_channels=A, kernel_size=9, stride=1, padding=2, bias=False)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            layer_list['bn1'] = nn.BatchNorm2d(num_features=A, eps=0.001, momentum=0.1, affine=True)
            layer_list['relu1'] = nn.ReLU(inplace=True)

            layer_list['prim1'] = layers.PrimMatrix2d(output_dim=B, h=h, kernel_size=9, stride=2, padding=2, bias=True)
            layer_list['bnn1'] = layers2.BNLayer()
            layer_list['route1'] = layers.MatrixRouting(output_dim=B, num_routing=1)

            layer_list['prim2'] = layers.PrimMatrix2d(output_dim=C, h=h, kernel_size=7, stride=2, padding=1, bias=False, advanced=True)
            layer_list['bnn2'] = layers2.BNLayer()
            layer_list['route2'] = layers.MatrixRouting(output_dim=C, num_routing=3)

            layer_list['prim3'] = layers.PrimMatrix2d(output_dim=D, h=h, kernel_size=5, stride=2, padding=1, bias=False, advanced=True)
            layer_list['bnn3'] = layers2.BNLayer()
            layer_list['route3'] = layers.MatrixRouting(output_dim=D, num_routing=3)

            #self.decoder_input_atoms = 16
            layer_list['prim4'] = layers.PrimMatrix2d(output_dim=E, h=h, kernel_size=0, stride=1, padding=0, bias=False, advanced=True)
            layer_list['bnn4'] = layers2.BNLayer()
            layer_list['route4'] = layers.MatrixRouting(output_dim=E, num_routing=3)
            self.capsules = nn.Sequential(layer_list)

            self.capsules = nn.Sequential(layer_list)

            self.image_decoder = nn.Sequential(
                layers2.MaskLayer(E),
                nn.Linear(h * E, 512),
                nn.ReLU(inplace=True),
                nn.Linear(512, 1024),
                nn.ReLU(inplace=True),
                nn.Linear(1024, img_size),
                nn.Sigmoid()
            )
        elif args.dataset == 'matmul_test':
            layer_list = OrderedDict()
            container = []
            layer_list['store'] = layers2.StoreLayer(container, True)

            layer_list['conv1'] = nn.Conv2d(in_channels=1, out_channels=1, kernel_size=3, stride=1, padding=1, bias=False)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            layer_list['tanh1'] = nn.Tanh()

            layer_list['concat'] = layers2.ConcatLayer(container, do_clone=True)

            layer_list['conv2'] = nn.Conv2d(in_channels=2, out_channels=1, kernel_size=3, stride=1, padding=1, bias=False)
            nn.init.normal_(layer_list['conv2'].weight.data, mean=0,std=0.1)
            layer_list['tanh2'] = nn.Tanh()

            layer_list['concat1'] = layers2.ConcatLayer(container, do_clone=True)

            layer_list['conv3'] = nn.Conv2d(in_channels=3, out_channels=1, kernel_size=3, stride=1, padding=1, bias=False)
            nn.init.normal_(layer_list['conv3'].weight.data, mean=0,std=0.1)
            layer_list['tanh3'] = nn.Tanh()
            
            
            self.capsules = nn.Sequential(layer_list)
            self.image_decoder = None
            
        elif args.dataset == 'matmul':
            layer_list = OrderedDict()
            container = []
            layer_list['store'] = layers2.StoreLayer(container, True)

            layer_list['conv1'] = nn.Conv2d(in_channels=9, out_channels=9, kernel_size=3, stride=1, padding=1, bias=False)
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            #layer_list['tanh1'] = nn.ReLU()
            
            layer_list['concat'] = layers2.ConcatLayer(container, do_clone=True)

            layer_list['conv2'] = nn.Conv2d(in_channels=2*9, out_channels=9, kernel_size=3, stride=1, padding=1, bias=True)
            nn.init.normal_(layer_list['conv2'].weight.data, mean=0,std=0.1)
            layer_list['tanh2'] = nn.Tanh()
            
            """
            layer_list['concat1'] = layers2.AddLayer(container, do_clone=True)

            layer_list['conv3'] = nn.Conv2d(in_channels=9, out_channels=9, kernel_size=3, stride=1, padding=1, bias=False)
            nn.init.normal_(layer_list['conv3'].weight.data, mean=0,std=0.1)
            layer_list['tanh3'] = nn.Tanh()
            """
            self.capsules = nn.Sequential(layer_list)
            self.image_decoder = None

        elif args.dataset == 'msra':
            """
            OBS: primary caps 2 and 3 should be WITHOUT BIAS!! Bias is NOT good...!
            """
            #A, B, C, D, E, F, h = 13, 64, 64, 64, 64, 5, 12
            #A, B, C, D, E, F, h = 13, 32, 48, 48, 48, 5, 12
            A, B, C, D, E, F, h = 13, 32, 32, 32, 32, 5, 12
            
            
            layer_list = OrderedDict()
            layer_list['posenc'] = layers.PosEncoderLayer()
            layer_list['conv1'] = nn.Conv2d(in_channels=1+1, out_channels=A, kernel_size=7, stride=2, padding=0, bias=False) # -> 61
            nn.init.normal_(layer_list['conv1'].weight.data, mean=0,std=0.1)
            layer_list['bn1'] = nn.BatchNorm2d(num_features=A, eps=0.001, momentum=0.1, affine=True)
            layer_list['relu1'] = nn.ReLU(inplace=True)

            layer_list['prim1'] = layers.PrimMatrix2d(output_dim=B, h=h, kernel_size=5, stride=2, padding=0, bias=True) # -> 29
            layer_list['bnn1'] = layers2.BNLayer()
            layer_list['route1'] = layers.MatrixRouting(output_dim=B, num_routing=1)

            layer_list['prim2'] = layers.PrimMatrix2d(output_dim=C, h=h, kernel_size=3, stride=2, padding=1, bias=False, advanced=True, pool=True) # -> 13
            layer_list['bnn2'] = layers2.BNLayer2()
            route2 = layers.MatrixRouting(output_dim=C, num_routing=3, batchnorm=af.BatchRenorm(num_features=C, update_interval=3, momentum=0.1*(args.batch_size/20)),
                                            sparse=layers.SparseCoding(C, type='lifetime',
                                            target_max_boost=2., boost_update_count=len_dataset, return_mask=False, active=True), stat=stat)
            layer_list['route2'] = route2
            
            layer_list['prim2a'] = layers.PrimMatrix2d(output_dim=D, h=h, kernel_size=3, stride=2, padding=0, bias=False, advanced=True, pool=True) # -> 7
            layer_list['bnn2a'] = layers2.BNLayer2()
            route2a = layers.MatrixRouting(output_dim=D, num_routing=3, batchnorm=af.BatchRenorm(num_features=D, update_interval=3, momentum=0.1*(args.batch_size/20)),
                                            sparse=layers.SparseCoding(D, type='lifetime',
                                            target_max_boost=2., boost_update_count=len_dataset, return_mask=False, active=True), stat=stat)
            layer_list['route2a'] = route2a


            """
            layer_list['prim2b'] = layers.PrimMatrix2d(output_dim=D, h=h, kernel_size=3, stride=2, padding=0, bias=False, advanced=True, pool=True) # -> 7
            layer_list['bnn2b'] = layers2.BNLayer2()
            route2b = layers.MatrixRouting(output_dim=D, num_routing=3, batchnorm=af.BatchRenorm(num_features=D, update_interval=3, momentum=0.1*(args.batch_size/20)),
                                            sparse=layers.SparseCoding(D, type='lifetime',
                                            target_max_boost=2., boost_update_count=len_dataset, return_mask=False, active=True), stat=stat)
            layer_list['route2b'] = route2b
            """

            
            #0.996
            layer_list['prim3'] = layers.PrimMatrix2d(output_dim=E, h=h, kernel_size=3, stride=1, padding=0, bias=False, advanced=True, pool=True) # -> 5
            layer_list['bnn3'] = layers2.BNLayer2()
            route3 = layers.MatrixRouting(output_dim=E, num_routing=3, batchnorm=af.BatchRenorm(num_features=E, update_interval=3, momentum=0.1*(args.batch_size/20)),
                                            sparse=layers.SparseCoding(E, type='lifetime',
                                            target_max_boost=2., boost_update_count=len_dataset, return_mask=False, active=True), stat=stat)
            layer_list['route3'] = route3

            #container = []
            #layer_list['store'] = layers2.StoreLayer(container)

            self.decoder_input_atoms = 15
            layer_list['prim4'] = layers.PrimMatrix2d(output_dim=F, h=self.decoder_input_atoms, kernel_size=0, stride=1, padding=0, bias=False, advanced=True, pool=True)
            layer_list['bnn4'] = layers2.BNLayer2()
            layer_list['route4'] = layers.MatrixRouting(output_dim=F, num_routing=3)
            #layer_list['route4'] = layers.MatrixRouting(output_dim=E, num_routing=3, activation=af.NormedActivation(E, momentum=0.1*(args.batch_size/20), update_interval=3, activation=af.Sigmoid()))

            layer_list['cat'] = layers2.CatLayer()
            
            self.capsules = nn.Sequential(layer_list)

            """
            decoder_list = OrderedDict()
            
            decoder_list['activate'] = layers2.ActivatePathway(container)
            #decoder_list['mask'] = layers2.MaskLayer()
            
            #decoder_list['prepare'] = layers2.Pose2VectorRepLayer()
            decoder_list['1transposed'] = layers.PrimMatrix2d(output_dim=32, h=15, kernel_size=10, stride=1, padding=0, bias=False, advanced=True, func='ConvTranspose2d')
            decoder_list['bnn1_transposed'] = layers2.BNLayer()
            decoder_list['route1_transposed'] = layers.MatrixRouting(output_dim=32, num_routing=3)
            #decoder_list['sparse1_transposed'] = sparse.SparseCoding()
    
            decoder_list['2transposed'] = layers.PrimMatrix2d(output_dim=16, h=12, kernel_size=7, stride=1, padding=0, bias=False, advanced=True, func='ConvTranspose2d')
            decoder_list['bnn2_transposed'] = layers2.BNLayer()
            decoder_list['route2_transposed'] = layers.MatrixRouting(output_dim=16, num_routing=3)
            #decoder_list['sparse2_transposed'] = sparse.SparseCoding()
    
            decoder_list['3transposed'] = layers.PrimMatrix2d(output_dim=1, h=12, kernel_size=7, stride=2, padding=0, bias=False, advanced=True, func='ConvTranspose2d')
            decoder_list['bnn3_transposed'] = layers2.BNLayer()
            decoder_list['route3_transposed'] = layers.MatrixRouting(output_dim=1, num_routing=3)
    
            decoder_list['transform'] = layers.MatrixToConv()
    
            decoder_list['conv1_transposed'] = nn.ConvTranspose2d(in_channels=13, out_channels=1, kernel_size=11, stride=2, padding=0, output_padding=1, bias=True)
            nn.init.normal_(decoder_list['conv1_transposed'].weight.data, mean=0,std=0.1)
            """
            self.image_decoder = None #nn.Sequential(decoder_list)
            
    def forward(self, x, disable_recon=False):
        p = self.capsules(x)
        if not disable_recon and self.image_decoder is not None:
            return p, self.image_decoder(p)
        return p
